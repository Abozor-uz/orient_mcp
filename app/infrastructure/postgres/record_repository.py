# app/infrastructure/postgres/record_repository.py
# ============================================================================
# Read-only PostgreSQL Record Repository
#
# Executes only structured SELECT queries compiled from catalog-validated
# entities, fields, filters, aggregates, and registered foreign-key relations.
# ============================================================================

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from app.domain.models import (
    AggregateFunction,
    AggregateMetric,
    AggregateRow,
    AggregationResult,
    CatalogSnapshot,
    DatabaseContext,
    EntityInfo,
    FilterSpec,
    RecordPage,
    RecordView,
    RelationDirection,
    RelationInfo,
    SortDirection,
    SortSpec,
)
from app.infrastructure.postgres.pool import PostgresPool
from app.infrastructure.postgres.query_builder import (
    compile_filters,
    compile_order,
    qualified_table,
    select_fields,
)


class PostgresRecordRepository:
    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

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
    ) -> RecordPage:
        effective_order = list(order_by)
        selected_sort_fields = {item.field for item in effective_order}
        effective_order.extend(
            item for item in self._default_order(entity) if item.field not in selected_sort_fields
        )
        where_sql, parameters = compile_filters(filters)
        query = (
            sql.SQL("SELECT {} FROM {}").format(select_fields(fields), qualified_table(entity.name))
            + where_sql
            + compile_order(effective_order)
            + sql.SQL(" LIMIT %s OFFSET %s")
        )
        parameters.extend([limit + 1, offset])
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(query, parameters)
            rows = list(await cursor.fetchall())
        has_more = len(rows) > limit
        visible = rows[:limit]
        return RecordPage(
            entity=entity.name,
            records=[RecordView(entity=entity.name, values=dict(row)) for row in visible],
            fields=fields,
            row_count=len(visible),
            has_more=has_more,
            next_cursor=None,
            as_of=datetime.now(UTC),
            schema_fingerprint=fingerprint,
        )

    async def get_one(
        self,
        *,
        entity: EntityInfo,
        key: dict[str, Any],
        fields: list[str],
    ) -> RecordView | None:
        key_filters = [
            FilterSpec(field=field, operator="eq", value=value) for field, value in key.items()
        ]
        where_sql, parameters = compile_filters(key_filters)
        query = (
            sql.SQL("SELECT {} FROM {}").format(select_fields(fields), qualified_table(entity.name))
            + where_sql
            + sql.SQL(" LIMIT 2")
        )
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(query, parameters)
            rows = list(await cursor.fetchall())
        if len(rows) != 1:
            return None
        return RecordView(entity=entity.name, values=dict(rows[0]))

    async def aggregate(
        self,
        *,
        entity: EntityInfo,
        metrics: list[AggregateMetric],
        group_by: list[str],
        filters: list[FilterSpec],
        limit: int,
        fingerprint: str,
    ) -> AggregationResult:
        selections: list[sql.Composable] = [sql.Identifier(field) for field in group_by]
        for index, metric in enumerate(metrics):
            alias = metric.alias or f"{metric.function.value}_{metric.field or 'all'}_{index}"
            expression: sql.Composable
            if metric.function == AggregateFunction.COUNT and metric.field is None:
                expression = sql.SQL("COUNT(*)")
            else:
                expression = sql.SQL("{}({})").format(
                    sql.SQL(metric.function.value.upper()),
                    sql.Identifier(metric.field or ""),
                )
            selections.append(sql.SQL("{} AS {}").format(expression, sql.Identifier(alias)))
        where_sql, parameters = compile_filters(filters)
        query: sql.Composable = (
            sql.SQL("SELECT {} FROM {}").format(
                sql.SQL(", ").join(selections),
                qualified_table(entity.name),
            )
            + where_sql
        )
        if group_by:
            query += sql.SQL(" GROUP BY {} ORDER BY {}").format(
                sql.SQL(", ").join(sql.Identifier(field) for field in group_by),
                sql.SQL(", ").join(sql.Identifier(field) for field in group_by),
            )
        query += sql.SQL(" LIMIT %s")
        parameters.append(limit + 1)
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(query, parameters)
            rows = list(await cursor.fetchall())
        truncated = len(rows) > limit
        visible = rows[:limit]
        return AggregationResult(
            entity=entity.name,
            rows=[AggregateRow(values=dict(row)) for row in visible],
            row_count=len(visible),
            truncated=truncated,
            as_of=datetime.now(UTC),
            schema_fingerprint=fingerprint,
        )

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
    ) -> RecordPage:
        current_alias = "current_row"
        related_alias = "related_row"
        if relation.direction == RelationDirection.OUTBOUND:
            join_pairs = zip(relation.source_fields, relation.target_fields, strict=True)
        else:
            join_pairs = zip(relation.target_fields, relation.source_fields, strict=True)
        join_clauses = [
            sql.SQL("{}.{} = {}.{}").format(
                sql.Identifier(current_alias),
                sql.Identifier(current_field),
                sql.Identifier(related_alias),
                sql.Identifier(related_field),
            )
            for current_field, related_field in join_pairs
        ]
        key_filters = [
            FilterSpec(field=field, operator="eq", value=value) for field, value in key.items()
        ]
        where_sql, parameters = compile_filters(key_filters, alias=current_alias)
        order = self._default_order(related_entity)
        query = (
            sql.SQL("SELECT {} FROM {} AS {} JOIN {} AS {} ON {}").format(
                select_fields(fields, alias=related_alias),
                qualified_table(current_entity.name),
                sql.Identifier(current_alias),
                qualified_table(related_entity.name),
                sql.Identifier(related_alias),
                sql.SQL(" AND ").join(join_clauses),
            )
            + where_sql
            + compile_order(order, alias=related_alias)
            + sql.SQL(" LIMIT %s OFFSET %s")
        )
        parameters.extend([limit + 1, offset])
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(query, parameters)
            rows = list(await cursor.fetchall())
        has_more = len(rows) > limit
        visible = rows[:limit]
        return RecordPage(
            entity=related_entity.name,
            records=[RecordView(entity=related_entity.name, values=dict(row)) for row in visible],
            fields=fields,
            row_count=len(visible),
            has_more=has_more,
            next_cursor=None,
            as_of=datetime.now(UTC),
            schema_fingerprint=fingerprint,
        )

    async def get_context(
        self,
        *,
        source: str,
        snapshot: CatalogSnapshot,
    ) -> DatabaseContext:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT current_database() AS database,
                       current_user AS user,
                       session_user AS session_user,
                       pg_is_in_recovery() AS replica,
                       current_setting('server_version') AS server_version,
                       current_setting('TimeZone') AS timezone,
                       current_setting('transaction_read_only') = 'on' AS transaction_read_only
                """
            )
            row = await cursor.fetchone()
            # SET ROLE can hide pg_stat_ssl details even for our own session.
            tls = connection.pgconn.ssl_in_use
        if row is None:
            raise RuntimeError("database_context_unavailable")
        return DatabaseContext(
            source=source,
            database=row["database"],
            user=row["user"],
            session_user=row["session_user"],
            replica=bool(row["replica"]),
            tls=tls,
            server_version=row["server_version"],
            timezone=row["timezone"],
            transaction_read_only=bool(row["transaction_read_only"]),
            schema_fingerprint=snapshot.fingerprint,
            catalog_loaded_at=snapshot.loaded_at,
            entity_count=len(snapshot.entities),
            checked_at=datetime.now(UTC),
        )

    @staticmethod
    def _default_order(entity: EntityInfo) -> list[SortSpec]:
        fields = entity.primary_key or ([entity.fields[0].name] if entity.fields else [])
        return [SortSpec(field=field, direction=SortDirection.ASC) for field in fields]
