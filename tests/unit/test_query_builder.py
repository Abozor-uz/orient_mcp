# tests/unit/test_query_builder.py
# ============================================================================
# Structured SQL Builder Tests
#
# Confirms identifiers are quoted and all caller values remain parameters.
# ============================================================================

from __future__ import annotations

from app.domain.models import FilterOperator, FilterSpec
from app.infrastructure.postgres.query_builder import compile_filters, qualified_table


def test_query_builder_quotes_identifiers_and_binds_values() -> None:
    table = qualified_table("public.orders").as_string()
    where, parameters = compile_filters(
        [FilterSpec(field="status", operator=FilterOperator.EQ, value="open'; DROP TABLE x")]
    )

    assert table == '"public"."orders"'
    assert where.as_string() == ' WHERE "status" = %s'
    assert parameters == ["open'; DROP TABLE x"]
