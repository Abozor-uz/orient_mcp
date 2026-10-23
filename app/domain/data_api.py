# app/domain/data_api.py
# ============================================================================
# Orient Source HTTP Contract
#
# Carries bounded operations and typed results without transporting SQL or
# client-supplied physical catalog metadata.
# ============================================================================
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.domain.customer_lookup import CustomerQuery, VehicleQuery
from app.domain.models import AggregateMetric, EntityInfo, FilterSpec, SortSpec

DataAction = Literal[
    "catalog", "search", "get-one", "aggregate", "related", "context", "customers", "vehicles"
]
DataEnvironment = Literal["dev", "production"]


class DataReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=63)
    action: DataAction
    environment: DataEnvironment
    entity_name: str | None = Field(default=None, min_length=1, max_length=257)
    fields: list[str] = Field(default_factory=list, max_length=30)
    filters: list[FilterSpec] = Field(default_factory=list, max_length=5)
    order_by: list[SortSpec] = Field(default_factory=list, max_length=3)
    limit: int = Field(default=20, strict=True, ge=1, le=100)
    offset: int = Field(default=0, strict=True, ge=0, le=10000)
    fingerprint: str | None = Field(default=None, max_length=128)
    key: dict[str, JsonValue] = Field(default_factory=dict, max_length=30)
    relation_name: str | None = Field(default=None, min_length=1, max_length=257)
    metrics: list[AggregateMetric] = Field(default_factory=list, max_length=5)
    group_by: list[str] = Field(default_factory=list, max_length=3)
    customers: CustomerQuery | None = None
    vehicles: VehicleQuery | None = None
    after_entity: str | None = Field(default=None, max_length=257)


class DataReadReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1] = 1
    environment: DataEnvironment
    source: str
    action: DataAction
    source_database: str
    payload: JsonValue


class CatalogReadPage(BaseModel):
    entities: list[EntityInfo]
    fingerprint: str
    loaded_at: datetime
    next_after_entity: str | None = None
