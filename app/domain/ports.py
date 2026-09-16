# app/domain/ports.py
# ============================================================================
# Orient MCP Repository Ports
#
# Protocols isolate services from PostgreSQL and control-store implementations.
# ============================================================================

from __future__ import annotations

from typing import Any, Protocol

from app.domain.models import (
    AggregateMetric,
    AggregationResult,
    CatalogSnapshot,
    DatabaseContext,
    EntityInfo,
    FilterSpec,
    RecordPage,
    RecordView,
    RelationInfo,
    SortSpec,
)


class CatalogRepositoryPort(Protocol):
    async def load_catalog(self) -> CatalogSnapshot: ...


class RecordRepositoryPort(Protocol):
    async def search(
        self,
        *,
        entity: EntityInfo,
        fields: list[str],
        filters: list[FilterSpec],
        order_by: list[SortSpec],
        limit: int,
        offset: int,
        fingerprint: str,
    ) -> RecordPage: ...

    async def get_one(
        self,
        *,
        entity: EntityInfo,
        key: dict[str, Any],
        fields: list[str],
    ) -> RecordView | None: ...

    async def aggregate(
        self,
        *,
        entity: EntityInfo,
        metrics: list[AggregateMetric],
        group_by: list[str],
        filters: list[FilterSpec],
        limit: int,
        fingerprint: str,
    ) -> AggregationResult: ...

    async def related(
        self,
        *,
        current_entity: EntityInfo,
        key: dict[str, Any],
        relation: RelationInfo,
        related_entity: EntityInfo,
        fields: list[str],
        limit: int,
        offset: int,
        fingerprint: str,
    ) -> RecordPage: ...

    async def get_context(
        self,
        *,
        source: str,
        snapshot: CatalogSnapshot,
    ) -> DatabaseContext: ...


class AuditRepositoryPort(Protocol):
    async def append_audit(self, payload: dict[str, Any]) -> bool: ...
