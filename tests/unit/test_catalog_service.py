# tests/unit/test_catalog_service.py
# ============================================================================
# Catalog Service Tests
#
# Verifies cached loading and multilingual exact alias resolution.
# ============================================================================

from __future__ import annotations

from app.domain.models import CatalogSnapshot
from app.services.catalog_service import CatalogService


class CatalogRepositoryStub:
    def __init__(self, snapshot: CatalogSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def load_catalog(self) -> CatalogSnapshot:
        self.calls += 1
        return self.snapshot


async def test_catalog_resolves_alias_and_caches_snapshot(
    catalog_snapshot: CatalogSnapshot,
) -> None:
    repository = CatalogRepositoryStub(catalog_snapshot)
    service = CatalogService(repository, ttl_seconds=60)

    entity, snapshot = await service.resolve_entity("ЗАКАЗЫ")
    await service.get_snapshot()

    assert entity.name == "public.orders"
    assert snapshot.fingerprint == "catalog-v1"
    assert repository.calls == 1
