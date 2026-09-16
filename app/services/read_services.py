# app/services/read_services.py
# ============================================================================
# Read Query Services
#
# Orchestrates catalog resolution, policy validation, cursor handling, and the
# read-only repositories used by MCP tools.
# ============================================================================

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.domain.errors import CatalogError, QueryValidationError
from app.domain.models import (
    AggregateMetric,
    AggregationResult,
    DatabaseContext,
    FilterSpec,
    RecordPage,
    RecordView,
    RelationDirection,
    SortSpec,
)
from app.domain.ports import RecordRepositoryPort
from app.services.catalog_service import CatalogService
from app.services.cursor_service import CursorCodec
from app.services.validation_service import QueryValidationService


class RecordSearchService:
    def __init__(
        self,
        catalog: CatalogService,
        repository: RecordRepositoryPort,
        validator: QueryValidationService,
        cursors: CursorCodec,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._validator = validator
        self._cursors = cursors

    async def search(
        self,
        *,
        entity_name: str,
        fields: list[str],
        filters: list[FilterSpec],
        order_by: list[SortSpec],
        limit: int,
        cursor: str | None,
    ) -> RecordPage:
        entity, snapshot = await self._catalog.resolve_entity(entity_name)
        fields = self._validator.validate_fields(entity, fields)
        filters = self._validator.validate_filters(entity, filters)
        order_by = self._validator.validate_sort(entity, order_by)
        limit = self._validator.validate_limit(limit)
        binding = _binding(
            {
                "fields": fields,
                "filters": [item.model_dump(mode="json") for item in filters],
                "order": [item.model_dump(mode="json") for item in order_by],
            }
        )
        offset = self._cursors.decode(
            cursor, entity=entity.name, fingerprint=snapshot.fingerprint, binding=binding
        )
        page = await self._repository.search(
            entity=entity,
            fields=fields,
            filters=filters,
            order_by=order_by,
            limit=limit,
            offset=offset,
            fingerprint=snapshot.fingerprint,
        )
        if page.has_more:
            page.next_cursor = self._cursors.encode(
                entity=entity.name,
                offset=offset + limit,
                fingerprint=snapshot.fingerprint,
                binding=binding,
            )
        return page

    async def get_one(
        self,
        *,
        entity_name: str,
        key: dict[str, Any],
        fields: list[str],
    ) -> RecordView | None:
        entity, _ = await self._catalog.resolve_entity(entity_name)
        fields = self._validator.validate_fields(entity, fields)
        key = self._validator.validate_key(entity, key)
        return await self._repository.get_one(entity=entity, key=key, fields=fields)


class AggregationService:
    def __init__(
        self,
        catalog: CatalogService,
        repository: RecordRepositoryPort,
        validator: QueryValidationService,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._validator = validator

    async def aggregate(
        self,
        *,
        entity_name: str,
        metrics: list[AggregateMetric],
        group_by: list[str],
        filters: list[FilterSpec],
        limit: int,
    ) -> AggregationResult:
        entity, snapshot = await self._catalog.resolve_entity(entity_name)
        metrics, group_by = self._validator.validate_aggregation(entity, metrics, group_by)
        filters = self._validator.validate_filters(entity, filters)
        limit = self._validator.validate_limit(limit)
        return await self._repository.aggregate(
            entity=entity,
            metrics=metrics,
            group_by=group_by,
            filters=filters,
            limit=limit,
            fingerprint=snapshot.fingerprint,
        )


class RelationService:
    def __init__(
        self,
        catalog: CatalogService,
        repository: RecordRepositoryPort,
        validator: QueryValidationService,
        cursors: CursorCodec,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._validator = validator
        self._cursors = cursors

    async def related(
        self,
        *,
        entity_name: str,
        key: dict[str, Any],
        relation_name: str,
        fields: list[str],
        limit: int,
        cursor: str | None,
    ) -> RecordPage:
        current, snapshot = await self._catalog.resolve_entity(entity_name)
        key = self._validator.validate_key(current, key)
        relation = self._validator.resolve_relation(current, relation_name)
        related_name = (
            relation.target_entity
            if relation.direction == RelationDirection.OUTBOUND
            else relation.source_entity
        )
        related, related_snapshot = await self._catalog.resolve_entity(related_name)
        if related_snapshot.fingerprint != snapshot.fingerprint:
            raise CatalogError("catalog_changed_during_request")
        fields = self._validator.validate_fields(related, fields)
        limit = self._validator.validate_limit(limit)
        binding = _binding({"key": key, "fields": fields})
        offset = self._cursors.decode(
            cursor,
            entity=current.name,
            fingerprint=snapshot.fingerprint,
            relation=relation.name,
            binding=binding,
        )
        page = await self._repository.related(
            current_entity=current,
            key=key,
            relation=relation,
            related_entity=related,
            fields=fields,
            limit=limit,
            offset=offset,
            fingerprint=snapshot.fingerprint,
        )
        if page.has_more:
            page.next_cursor = self._cursors.encode(
                entity=current.name,
                offset=offset + limit,
                fingerprint=snapshot.fingerprint,
                relation=relation.name,
                binding=binding,
            )
        return page


class ContextService:
    def __init__(
        self,
        catalog: CatalogService,
        repository: RecordRepositoryPort,
        source: str,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._source = source

    async def get_context(self) -> DatabaseContext:
        snapshot = await self._catalog.get_snapshot()
        context = await self._repository.get_context(source=self._source, snapshot=snapshot)
        if not context.transaction_read_only:
            raise QueryValidationError("database_transaction_is_not_read_only")
        return context


def _binding(query: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(query, sort_keys=True, default=str).encode()).hexdigest()
