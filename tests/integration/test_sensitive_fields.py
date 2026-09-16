# tests/integration/test_sensitive_fields.py
# ============================================================================
# Sensitive Field Access Regression Tests
#
# Confirms real table and view fields are excluded from discovery and every
# generic read path while customer and vehicle lookups remain usable.
# ============================================================================

from __future__ import annotations

import pytest

from app.bootstrap.dependencies import ApplicationDependencies
from app.domain.customer_lookup import CustomerQuery, VehicleQuery
from app.domain.errors import QueryValidationError
from app.domain.models import AggregateMetric, FilterSpec, RelationDirection, SortSpec

_VEHICLES = "public.business_account_garagecar"
_SENSITIVE_FIELDS = {"pinpp", "prev_pnfl", "extra_data"}


@pytest.mark.parametrize("entity_name", [_VEHICLES, "garage_export.vehicle_export"])
async def test_catalog_and_available_record_fields_exclude_sensitive_values(
    dependencies: ApplicationDependencies, entity_name: str
) -> None:
    entity, _ = await dependencies.catalog_service.get_entity(entity_name)
    fields = [field.name for field in entity.fields]
    assert _SENSITIVE_FIELDS.isdisjoint(fields)
    assert {"owner_id", "plate_number", "win_number"}.issubset(fields)
    page = await dependencies.record_service.search(
        entity_name=entity_name,
        fields=fields,
        filters=[],
        order_by=[],
        limit=10,
        cursor=None,
    )
    assert page.row_count == 4
    assert "sensitive-synthetic" not in page.model_dump_json()


@pytest.mark.parametrize("field", sorted(_SENSITIVE_FIELDS))
async def test_sensitive_fields_cannot_be_used_by_generic_read_operations(
    dependencies: ApplicationDependencies, field: str
) -> None:
    for entity_name in (_VEHICLES, "garage_export.vehicle_export"):
        with pytest.raises(QueryValidationError, match="^field_not_allowed$"):
            await dependencies.record_service.search(
                entity_name=entity_name,
                fields=["id", field],
                filters=[],
                order_by=[],
                limit=10,
                cursor=None,
            )
        with pytest.raises(QueryValidationError, match="^filter_field_not_allowed$"):
            await dependencies.record_service.search(
                entity_name=entity_name,
                fields=["id"],
                filters=[FilterSpec(field=field, operator="is_null", value=False)],
                order_by=[],
                limit=10,
                cursor=None,
            )
        with pytest.raises(QueryValidationError, match="^sort_field_not_allowed$"):
            await dependencies.record_service.search(
                entity_name=entity_name,
                fields=["id"],
                filters=[],
                order_by=[SortSpec(field=field)],
                limit=10,
                cursor=None,
            )
        with pytest.raises(QueryValidationError, match="^aggregate_field_not_allowed$"):
            await dependencies.aggregation_service.aggregate(
                entity_name=entity_name,
                metrics=[AggregateMetric(function="count", field=field)],
                group_by=[],
                filters=[],
                limit=10,
            )
        with pytest.raises(QueryValidationError, match="^group_field_not_allowed$"):
            await dependencies.aggregation_service.aggregate(
                entity_name=entity_name,
                metrics=[AggregateMetric(function="count")],
                group_by=[field],
                filters=[],
                limit=10,
            )
    with pytest.raises(QueryValidationError, match="^field_not_allowed$"):
        await dependencies.record_service.get_one(
            entity_name=_VEHICLES, key={"id": 1}, fields=["id", field]
        )
    customer, _ = await dependencies.catalog_service.get_entity("public.users")
    relation = next(
        relation
        for relation in customer.relations
        if relation.direction == RelationDirection.INBOUND and relation.source_entity == _VEHICLES
    )
    with pytest.raises(QueryValidationError, match="^field_not_allowed$"):
        await dependencies.relation_service.related(
            entity_name=customer.name,
            key={"id": 1},
            relation_name=relation.name,
            fields=["id", field],
            limit=10,
            cursor=None,
        )


async def test_sensitive_vehicle_fields_do_not_break_customer_or_identifier_lookups(
    dependencies: ApplicationDependencies,
) -> None:
    service = dependencies.resolve_source(None).customer_lookup_service
    customers = await service.customers(CustomerQuery(phone="90 123 45 67"))
    assert [customer.customer_id for customer in customers.customers] == [1]
    for query in (
        VehicleQuery(plate_number="01 A 123 BC"),
        VehicleQuery(vin="1hgcm82633a004352"),
        VehicleQuery(customer_id=1),
    ):
        result = await service.vehicles(query)
        assert {1, 2}.issubset(vehicle.vehicle_id for vehicle in result.vehicles)
        assert "sensitive-synthetic" not in result.model_dump_json()
