# app/domain/models.py
# ============================================================================
# Orient MCP Domain Models
#
# Typed contracts for schema discovery, structured read queries, relations,
# aggregation, provenance, and standard tool results.
# ============================================================================

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


class EntityKind(str, Enum):
    TABLE = "table"
    VIEW = "view"
    MATERIALIZED_VIEW = "materialized_view"
    PARTITIONED_TABLE = "partitioned_table"
    FOREIGN_TABLE = "foreign_table"


class FilterOperator(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    ILIKE = "ilike"
    IS_NULL = "is_null"


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class AggregateFunction(str, Enum):
    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


class RelationDirection(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class FilterSpec(BaseModel):
    field: str = Field(min_length=1, max_length=128)
    operator: FilterOperator
    value: Any = None


class SortSpec(BaseModel):
    field: str = Field(min_length=1, max_length=128)
    direction: SortDirection = SortDirection.ASC


class AggregateMetric(BaseModel):
    function: AggregateFunction
    field: str | None = Field(default=None, min_length=1, max_length=128)
    alias: str | None = Field(default=None, min_length=1, max_length=128)


class FieldInfo(BaseModel):
    name: str
    data_type: str
    nullable: bool
    ordinal_position: int
    description: str | None = None
    is_primary_key: bool = False
    is_indexed: bool = False
    is_numeric: bool = False
    is_text: bool = False
    enum_values: list[str] = Field(default_factory=list)


class RelationInfo(BaseModel):
    name: str
    source_entity: str
    source_fields: list[str]
    target_entity: str
    target_fields: list[str]
    direction: RelationDirection


class EntitySummary(BaseModel):
    name: str
    schema_name: str
    object_name: str
    kind: EntityKind
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    estimated_rows: int | None = None


class EntityInfo(EntitySummary):
    fields: list[FieldInfo]
    primary_key: list[str] = Field(default_factory=list)
    relations: list[RelationInfo] = Field(default_factory=list)


class CatalogSnapshot(BaseModel):
    entities: dict[str, EntityInfo]
    fingerprint: str
    loaded_at: datetime


class RecordView(BaseModel):
    entity: str
    values: dict[str, Any]


class RecordPage(BaseModel):
    entity: str
    records: list[RecordView]
    fields: list[str]
    row_count: int
    has_more: bool
    next_cursor: str | None = None
    as_of: datetime
    schema_fingerprint: str


class AggregateRow(BaseModel):
    values: dict[str, Any]


class AggregationResult(BaseModel):
    entity: str
    rows: list[AggregateRow]
    row_count: int
    truncated: bool
    as_of: datetime
    schema_fingerprint: str


class DatabaseContext(BaseModel):
    source: str
    database: str
    user: str
    session_user: str = ""
    tls: bool = False
    replica: bool = False
    server_version: str = ""
    timezone: str
    transaction_read_only: bool
    schema_fingerprint: str
    catalog_loaded_at: datetime
    entity_count: int
    checked_at: datetime


T = TypeVar("T")


class ToolResult(BaseModel, Generic[T]):
    summary: str
    data: T
    source: str
    as_of: datetime
    warnings: list[str] = Field(default_factory=list)
    count: int | None = None
