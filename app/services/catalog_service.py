# app/services/catalog_service.py
# ============================================================================
# Schema Catalog Service
#
# Caches the filtered PostgreSQL catalog, resolves aliases, and exposes only
# entities and fields already authorized by database grants and policy.
# ============================================================================

from __future__ import annotations

import asyncio
import time

from app.domain.errors import CatalogError
from app.domain.models import CatalogSnapshot, EntityInfo, EntityKind, EntitySummary
from app.domain.ports import CatalogRepositoryPort


class CatalogService:
    def __init__(self, repository: CatalogRepositoryPort, ttl_seconds: int) -> None:
        self._repository = repository
        self._ttl_seconds = ttl_seconds
        self._snapshot: CatalogSnapshot | None = None
        self._loaded_monotonic = 0.0
        self._lock = asyncio.Lock()

    async def get_snapshot(self, *, force: bool = False) -> CatalogSnapshot:
        if not force and self._snapshot is not None:
            if time.monotonic() - self._loaded_monotonic < self._ttl_seconds:
                return self._snapshot
        async with self._lock:
            if not force and self._snapshot is not None:
                if time.monotonic() - self._loaded_monotonic < self._ttl_seconds:
                    return self._snapshot
            snapshot = await self._repository.load_catalog()
            if not snapshot.entities:
                raise CatalogError("catalog_is_empty")
            self._snapshot = snapshot
            self._loaded_monotonic = time.monotonic()
            return snapshot

    async def list_entities(
        self,
        *,
        query: str | None,
        kind: EntityKind | None,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[EntitySummary], CatalogSnapshot]:
        snapshot = await self.get_snapshot()
        needle = (query or "").strip().casefold()
        matches = []
        for entity in snapshot.entities.values():
            if kind is not None and entity.kind != kind:
                continue
            haystack = " ".join([entity.name, entity.description or "", *entity.aliases]).casefold()
            if needle and needle not in haystack:
                continue
            matches.append(
                EntitySummary.model_validate(
                    entity.model_dump(exclude={"fields", "primary_key", "relations"})
                )
            )
        matches.sort(key=lambda item: item.name)
        return matches[offset : offset + limit], snapshot

    async def resolve_entity(self, name: str) -> tuple[EntityInfo, CatalogSnapshot]:
        snapshot = await self.get_snapshot()
        normalized = name.strip().casefold()
        for full_name, entity in snapshot.entities.items():
            if full_name.casefold() == normalized:
                return entity, snapshot
        matches = []
        for entity in snapshot.entities.values():
            candidates = {
                entity.name.casefold(),
                entity.object_name.casefold(),
                *(alias.casefold() for alias in entity.aliases),
            }
            if normalized in candidates:
                matches.append(entity)
        if not matches:
            raise CatalogError("entity_not_found")
        if len(matches) > 1:
            raise CatalogError("entity_name_ambiguous")
        return matches[0], snapshot

    async def get_entity(self, name: str) -> tuple[EntityInfo, CatalogSnapshot]:
        return await self.resolve_entity(name)
