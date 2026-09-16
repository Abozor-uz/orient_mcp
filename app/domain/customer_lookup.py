# app/domain/customer_lookup.py
# ============================================================================
# Customer and Vehicle Lookup Contracts
#
# Typed exact-match queries and bounded results for Orient customer identities.
# ============================================================================

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class CustomerQuery(BaseModel):
    phone: str | None = None
    customer_id: int | None = None
    limit: int = 20
    after_id: int = 0


class VehicleQuery(BaseModel):
    plate_number: str | None = None
    vin: str | None = None
    customer_id: int | None = None
    limit: int = 20
    after_id: int = 0


class CustomerMatch(BaseModel):
    customer_id: int
    phone: str
    full_name: str | None
    matched_primary_phone: bool
    matched_additional_phone: bool


class VehicleMatch(BaseModel):
    vehicle_id: int
    plate_number: str
    vin: str | None
    customer_id: int | None
    customer_phone: str | None
    customer_name: str | None
    business_owner_id: int | None
    brand_id: int | None
    model_id: int | None
    year: int | None


class CustomerPage(BaseModel):
    customers: list[CustomerMatch]
    has_more: bool
    next_after_id: int | None


class VehiclePage(BaseModel):
    vehicles: list[VehicleMatch]
    has_more: bool
    next_after_id: int | None


class CustomerLookupRepositoryPort(Protocol):
    async def customers(self, query: CustomerQuery) -> CustomerPage: ...

    async def vehicles(self, query: VehicleQuery) -> VehiclePage: ...
