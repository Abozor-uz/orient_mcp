# tests/integration/test_source_database.py
# ============================================================================
# Real Source Database Acceptance
#
# Exercises role activation, write rejection, catalog policy and structured
# reads against synthetic data in isolated local PostgreSQL databases.
# ============================================================================

from __future__ import annotations

from decimal import Decimal

import pytest
from psycopg import errors

from app.bootstrap.dependencies import ApplicationDependencies
from app.domain.errors import QueryValidationError
from app.domain.models import AggregateMetric, FilterSpec


async def test_noinherit_role_is_activated_for_every_transaction(
    dependencies: ApplicationDependencies,
) -> None:
    for _ in range(2):
        context = await dependencies.context_service.get_context()
        assert context.user == "pg_read_all_data"
        assert context.session_user.startswith("mcp_reader_")
        assert context.transaction_read_only


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE public.write_probe (id integer)",
        "CREATE TEMP TABLE temp_write_probe (id integer)",
        "INSERT INTO public.users(id,username,status) VALUES(99,'test','active')",
        "UPDATE public.users SET status='blocked' WHERE id=1",
        "DELETE FROM public.users WHERE id=1",
        "TRUNCATE public.carwash_carwashorder",
    ],
)
async def test_writes_are_rejected(dependencies: ApplicationDependencies, statement: str) -> None:
    with pytest.raises((errors.ReadOnlySqlTransaction, errors.InsufficientPrivilege)):
        async with dependencies.data_pool.transaction() as connection:
            await connection.execute(statement)


async def test_catalog_includes_materialized_views_but_hides_secrets(
    dependencies: ApplicationDependencies,
) -> None:
    snapshot = await dependencies.catalog_service.get_snapshot()
    assert "public.django_session" not in snapshot.entities
    assert {f.name for f in snapshot.entities["public.users"].fields} == {
        "id",
        "username",
        "status",
        "full_name",
    }
    assert {f.name for f in snapshot.entities["public.order_totals"].fields} == {
        "user_id",
        "amount",
    }
    assert snapshot.entities["public.compound"].primary_key == []
    assert snapshot.entities["public.carwash_carwashorder"].relations


async def test_filtered_search_pagination_aggregate_and_relations(
    dependencies: ApplicationDependencies,
) -> None:
    service = dependencies.record_service
    params = dict(
        entity_name="public.carwash_carwashorder",
        fields=["id", "amount"],
        filters=[FilterSpec(field="status", operator="eq", value="paid")],
        order_by=[],
        limit=1,
    )
    first = await service.search(**params, cursor=None)
    second = await service.search(**params, cursor=first.next_cursor)
    assert first.records[0].values["id"] == 1
    assert second.records[0].values["id"] == 2
    assert not second.has_more
    total = await dependencies.aggregation_service.aggregate(
        entity_name="public.carwash_carwashorder",
        metrics=[AggregateMetric(function="sum", field="amount", alias="total")],
        group_by=[],
        filters=params["filters"],
        limit=10,
    )
    assert total.rows[0].values["total"] == Decimal("30000")
    entity, _ = await dependencies.catalog_service.get_entity("public.users")
    relation = next(
        r
        for r in entity.relations
        if r.direction.value == "inbound" and r.source_entity == "public.carwash_carwashorder"
    )
    related = await dependencies.relation_service.related(
        entity_name=entity.name,
        key={"id": 1},
        relation_name=relation.name,
        fields=["id"],
        limit=10,
        cursor=None,
    )
    assert related.row_count == 2


async def test_field_injection_and_cross_source_cursor_are_rejected(
    dependencies: ApplicationDependencies,
) -> None:
    params = dict(entity_name="public.users", fields=["id"], filters=[], order_by=[], limit=1)
    page = await dependencies.record_service.search(**params, cursor=None)
    other = next(s for name, s in dependencies.sources.items() if name != "orient")
    with pytest.raises(QueryValidationError, match="invalid_cursor"):
        await other.record_service.search(**params, cursor=page.next_cursor)
    with pytest.raises(QueryValidationError, match="field_not_allowed"):
        await dependencies.record_service.search(**{**params, "fields": ["password"]}, cursor=None)
    with pytest.raises(QueryValidationError, match="invalid_cursor"):
        await dependencies.record_service.search(
            **{**params, "filters": [FilterSpec(field="id", operator="gt", value=1)]},
            cursor=page.next_cursor,
        )
    with pytest.raises(QueryValidationError, match="field_not_allowed"):
        await dependencies.record_service.search(
            **{**params, "fields": ["id; DROP TABLE users"]}, cursor=None
        )
    with pytest.raises(QueryValidationError, match="source_not_allowed"):
        dependencies.resolve_source("postgres")


async def test_catalog_pagination_reaches_all_entities(
    dependencies: ApplicationDependencies,
) -> None:
    names = []
    offset = 0
    while True:
        page, _ = await dependencies.catalog_service.list_entities(
            query=None, kind=None, limit=2, offset=offset
        )
        names.extend(e.name for e in page)
        if len(page) < 2:
            break
        offset += 2
    snapshot = await dependencies.catalog_service.get_snapshot()
    assert sorted(names) == sorted(snapshot.entities)
