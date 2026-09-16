# app/services/customer_lookup_service.py
# ============================================================================
# Customer Lookup Service
#
# Normalizes identifiers and checks the same catalog policy used by generic
# reads before allowing specialized joins. Identifiers are never fuzzy matched.
# ============================================================================

from __future__ import annotations

import re

from app.domain.customer_lookup import (
    CustomerLookupRepositoryPort,
    CustomerPage,
    CustomerQuery,
    VehiclePage,
    VehicleQuery,
)
from app.domain.errors import QueryValidationError
from app.services.catalog_service import CatalogService


def normalize_phone(value: str) -> str:
    if len(value) > 64 or not re.fullmatch(r"\+?[0-9 ()\.\-]+", value.strip()):
        raise QueryValidationError("invalid_phone")
    digits = re.sub(r"[^0-9]", "", value)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 9:
        digits = "998" + digits
    if not 10 <= len(digits) <= 15 or digits.startswith("0"):
        raise QueryValidationError("invalid_phone")
    return digits


def normalize_plate(value: str) -> str:
    if len(value) > 64:
        raise QueryValidationError("invalid_plate_number")
    normalized = re.sub(r"[ \t\r\n-]", "", value).upper()
    if not re.fullmatch(r"[A-Z0-9]{4,16}", normalized):
        raise QueryValidationError("invalid_plate_number")
    return normalized


def normalize_vin(value: str) -> str:
    if len(value) > 64:
        raise QueryValidationError("invalid_vin")
    normalized = re.sub(r"[ \t\r\n-]", "", value).upper()
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", normalized):
        raise QueryValidationError("invalid_vin")
    return normalized


class CustomerLookupService:
    def __init__(self, catalog: CatalogService, repository: CustomerLookupRepositoryPort) -> None:
        self._catalog = catalog
        self._repository = repository

    async def customers(self, query: CustomerQuery) -> CustomerPage:
        self._validate_page(query.limit, query.after_id, query.customer_id)
        if query.phone is None and query.customer_id is None:
            raise QueryValidationError("lookup_identifier_required")
        normalized = query.model_copy(
            update={"phone": normalize_phone(query.phone) if query.phone is not None else None}
        )
        await self._require("public.users", {"id", "username", "full_name"})
        if normalized.phone is not None:
            await self._require("public.user_additional_phone", {"user_id", "number"})
        return await self._repository.customers(normalized)

    async def vehicles(self, query: VehicleQuery) -> VehiclePage:
        self._validate_page(query.limit, query.after_id, query.customer_id)
        if query.plate_number is None and query.vin is None and query.customer_id is None:
            raise QueryValidationError("lookup_identifier_required")
        normalized = query.model_copy(
            update={
                "plate_number": normalize_plate(query.plate_number)
                if query.plate_number is not None
                else None,
                "vin": normalize_vin(query.vin) if query.vin is not None else None,
            }
        )
        await self._require("public.users", {"id", "username", "full_name"})
        await self._require(
            "public.business_account_garagecar",
            {
                "id",
                "owner_id",
                "business_owner_id",
                "plate_number",
                "win_number",
                "brand_id",
                "model_id",
                "year",
            },
        )
        return await self._repository.vehicles(normalized)

    async def _require(self, name: str, required: set[str]) -> None:
        entity, _ = await self._catalog.get_entity(name)
        if not required.issubset({field.name for field in entity.fields}):
            raise QueryValidationError("lookup_fields_not_available")

    @staticmethod
    def _validate_page(limit: int, after_id: int, customer_id: int | None) -> None:
        if not 1 <= limit <= 100 or not 0 <= after_id < 2**63:
            raise QueryValidationError("invalid_lookup_pagination")
        if customer_id is not None and not 1 <= customer_id < 2**63:
            raise QueryValidationError("invalid_customer_id")
