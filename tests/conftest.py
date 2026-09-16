# tests/conftest.py
# ============================================================================
# Shared Test Fixtures
#
# Builds representative catalog models without external services or credentials.
# ============================================================================

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.domain.models import CatalogSnapshot, EntityInfo, EntityKind, FieldInfo


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def orders_entity() -> EntityInfo:
    return EntityInfo(
        name="public.orders",
        schema_name="public",
        object_name="orders",
        kind=EntityKind.TABLE,
        aliases=["заказы", "buyurtmalar"],
        fields=[
            FieldInfo(
                name="id",
                data_type="bigint",
                nullable=False,
                ordinal_position=1,
                is_primary_key=True,
                is_indexed=True,
                is_numeric=True,
            ),
            FieldInfo(
                name="status",
                data_type="text",
                nullable=False,
                ordinal_position=2,
                is_text=True,
            ),
            FieldInfo(
                name="total",
                data_type="numeric",
                nullable=True,
                ordinal_position=3,
                is_numeric=True,
            ),
        ],
        primary_key=["id"],
    )


@pytest.fixture
def catalog_snapshot(orders_entity: EntityInfo) -> CatalogSnapshot:
    return CatalogSnapshot(
        entities={orders_entity.name: orders_entity},
        fingerprint="catalog-v1",
        loaded_at=datetime.now(UTC),
    )
