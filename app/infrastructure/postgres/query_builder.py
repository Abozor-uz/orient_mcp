# app/infrastructure/postgres/query_builder.py
# ============================================================================
# Structured SQL Builder
#
# Compiles validated filters and sorting into psycopg SQL objects. Identifiers
# never come from raw interpolation and values are always query parameters.
# ============================================================================

from __future__ import annotations

from typing import Any

from psycopg import sql

from app.domain.models import FilterOperator, FilterSpec, SortSpec

_BINARY_OPERATORS = {
    FilterOperator.EQ: sql.SQL("="),
    FilterOperator.NEQ: sql.SQL("<>"),
    FilterOperator.GT: sql.SQL(">"),
    FilterOperator.GTE: sql.SQL(">="),
    FilterOperator.LT: sql.SQL("<"),
    FilterOperator.LTE: sql.SQL("<="),
    FilterOperator.ILIKE: sql.SQL("ILIKE"),
}


def qualified_table(entity_name: str) -> sql.Composed:
    schema, table = entity_name.split(".", 1)
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))


def select_fields(fields: list[str], alias: str | None = None) -> sql.Composable:
    if alias is None:
        parts: list[sql.Composable] = [sql.Identifier(field) for field in fields]
    else:
        parts = [
            sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(field))
            for field in fields
        ]
    return sql.SQL(", ").join(parts)


def compile_filters(
    filters: list[FilterSpec],
    alias: str | None = None,
) -> tuple[sql.Composable, list[Any]]:
    clauses: list[sql.Composable] = []
    parameters: list[Any] = []
    for item in filters:
        identifier: sql.Composable
        if alias is None:
            identifier = sql.Identifier(item.field)
        else:
            identifier = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(item.field))
        if item.operator in _BINARY_OPERATORS:
            clauses.append(sql.SQL("{} {} %s").format(identifier, _BINARY_OPERATORS[item.operator]))
            parameters.append(item.value)
        elif item.operator == FilterOperator.IN:
            placeholders = sql.SQL(", ").join([sql.Placeholder()] * len(item.value))
            clauses.append(sql.SQL("{} IN ({})").format(identifier, placeholders))
            parameters.extend(item.value)
        elif item.operator == FilterOperator.IS_NULL:
            clauses.append(
                sql.SQL("{} IS NULL").format(identifier)
                if item.value
                else sql.SQL("{} IS NOT NULL").format(identifier)
            )
    if not clauses:
        return sql.SQL(""), parameters
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses), parameters


def compile_order(order_by: list[SortSpec], alias: str | None = None) -> sql.Composable:
    if not order_by:
        return sql.SQL("")
    parts: list[sql.Composable] = []
    for item in order_by:
        identifier: sql.Composable
        if alias is None:
            identifier = sql.Identifier(item.field)
        else:
            identifier = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(item.field))
        direction = sql.SQL("ASC") if item.direction.value == "asc" else sql.SQL("DESC")
        parts.append(sql.SQL("{} {} NULLS LAST").format(identifier, direction))
    return sql.SQL(" ORDER BY ") + sql.SQL(", ").join(parts)
