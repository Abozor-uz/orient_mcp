# tests/integration/test_customer_lookup.py
# ============================================================================
# Real Database Customer Lookup Acceptance
#
# Verifies identity joins, duplicate matches, pagination and policy enforcement
# against synthetic Orient-shaped PostgreSQL tables.
# ============================================================================

from __future__ import annotations

import pytest

from app.bootstrap.dependencies import ApplicationDependencies
from app.domain.customer_lookup import CustomerQuery, VehicleQuery
from app.domain.errors import QueryValidationError


async def test_primary_and_additional_phones_match_without_duplicate_customers(
    dependencies: ApplicationDependencies,
) -> None:
    service = dependencies.resolve_source(None).customer_lookup_service
    primary = await service.customers(CustomerQuery(phone="90 123 45 67"))
    assert [c.customer_id for c in primary.customers] == [1]
    assert primary.customers[0].matched_primary_phone
    assert primary.customers[0].matched_additional_phone
    shared = await service.customers(CustomerQuery(phone="+998 93 123 45 67", limit=1))
    assert shared.has_more and shared.next_after_id == 1
    assert not shared.customers[0].matched_primary_phone
    second = await service.customers(CustomerQuery(phone="00998931234567", after_id=1, limit=1))
    assert [c.customer_id for c in second.customers] == [2]
    assert not second.has_more and second.next_after_id is None


async def test_customer_id_and_phone_are_combined_with_and(
    dependencies: ApplicationDependencies,
) -> None:
    service = dependencies.resolve_source(None).customer_lookup_service
    assert (await service.customers(CustomerQuery(customer_id=2))).customers[0].customer_id == 2
    assert not (await service.customers(CustomerQuery(customer_id=2, phone="901234567"))).customers
    assert not (await service.customers(CustomerQuery(phone="901234569"))).customers


async def test_plate_vin_owner_and_unowned_vehicle_results(
    dependencies: ApplicationDependencies,
) -> None:
    service = dependencies.resolve_source(None).customer_lookup_service
    plate = await service.vehicles(VehicleQuery(plate_number="01a-123bc", limit=2))
    assert [v.vehicle_id for v in plate.vehicles] == [1, 2]
    assert plate.has_more and plate.next_after_id == 2
    assert plate.vehicles[0].customer_phone == "+998 (90) 123-45-67"
    assert plate.vehicles[0].customer_name == "Synthetic Customer A"
    unowned = await service.vehicles(VehicleQuery(plate_number="01 A 123 BC", after_id=2))
    assert unowned.vehicles[0].vehicle_id == 4
    assert unowned.vehicles[0].customer_id is None
    assert unowned.vehicles[0].business_owner_id == 1
    assert not unowned.has_more
    vin = await service.vehicles(VehicleQuery(vin="1hgcm82633a004352"))
    assert [v.vehicle_id for v in vin.vehicles] == [1, 2]
    owner = await service.vehicles(VehicleQuery(customer_id=1))
    assert [v.vehicle_id for v in owner.vehicles] == [1, 2]
    assert not (
        await service.vehicles(VehicleQuery(vin="1HGCM82633A004352", customer_id=2))
    ).vehicles


async def test_lookup_rejects_unbounded_queries_and_invalid_pagination(
    dependencies: ApplicationDependencies,
) -> None:
    service = dependencies.resolve_source(None).customer_lookup_service
    for query in [
        CustomerQuery(),
        CustomerQuery(customer_id=0),
        CustomerQuery(customer_id=1, limit=101),
        CustomerQuery(customer_id=1, after_id=-1),
    ]:
        with pytest.raises(QueryValidationError):
            await service.customers(query)
    for query in [VehicleQuery(), VehicleQuery(plate_number="%"), VehicleQuery(vin="' OR 1=1 --")]:
        with pytest.raises(QueryValidationError):
            await service.vehicles(query)


async def test_specialized_lookup_respects_catalog_field_policy(
    dependencies: ApplicationDependencies,
) -> None:
    selected = dependencies.resolve_source(None)
    snapshot = await selected.catalog_service.get_snapshot()
    entity = snapshot.entities["public.users"]
    fields = entity.fields
    entity.fields = [f for f in fields if f.name != "username"]
    try:
        with pytest.raises(QueryValidationError, match="lookup_fields_not_available"):
            await selected.customer_lookup_service.customers(CustomerQuery(customer_id=1))
        with pytest.raises(QueryValidationError, match="lookup_fields_not_available"):
            await selected.customer_lookup_service.vehicles(VehicleQuery(customer_id=1))
    finally:
        entity.fields = fields
