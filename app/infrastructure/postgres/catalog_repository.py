# app/infrastructure/postgres/catalog_repository.py
# ============================================================================
# PostgreSQL Catalog Repository
#
# Builds the exposed entity, field, primary-key, foreign-key, and index graph
# from live PostgreSQL metadata and the server-side access policy.
# ============================================================================

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.domain.models import (
    CatalogSnapshot,
    EntityInfo,
    EntityKind,
    EntitySummary,
    FieldInfo,
    RelationDirection,
    RelationInfo,
)
from app.infrastructure.policy import CatalogPolicy
from app.infrastructure.postgres.pool import PostgresPool

_KIND_MAP = {
    "r": EntityKind.TABLE,
    "v": EntityKind.VIEW,
    "m": EntityKind.MATERIALIZED_VIEW,
    "p": EntityKind.PARTITIONED_TABLE,
    "f": EntityKind.FOREIGN_TABLE,
}

_NUMERIC_TYPES = {
    "smallint",
    "integer",
    "bigint",
    "decimal",
    "numeric",
    "real",
    "double precision",
    "smallserial",
    "serial",
    "bigserial",
    "money",
}
_TEXT_TYPES = {"character varying", "character", "text", "citext", "name"}


class PostgresCatalogRepository:
    def __init__(self, pool: PostgresPool, policy: CatalogPolicy) -> None:
        self._pool = pool
        self._policy = policy

    async def load_catalog(self) -> CatalogSnapshot:
        async with self._pool.transaction() as connection:
            objects = await self._fetch_objects(connection)
            columns = await self._fetch_columns(connection)
            primary_keys = await self._fetch_primary_keys(connection)
            foreign_keys = await self._fetch_foreign_keys(connection)
            indexed_fields = await self._fetch_indexed_fields(connection)

        entities: dict[str, EntityInfo] = {}
        columns_by_entity: dict[str, list[dict[str, Any]]] = {}
        for row in columns:
            entity = f"{row['schema_name']}.{row['object_name']}"
            columns_by_entity.setdefault(entity, []).append(row)

        primary_by_entity: dict[str, list[str]] = {}
        for row in primary_keys:
            entity = f"{row['schema_name']}.{row['object_name']}"
            primary_by_entity.setdefault(entity, []).append(row["field_name"])

        indexed = {
            (f"{row['schema_name']}.{row['object_name']}", row["field_name"])
            for row in indexed_fields
        }

        for row in objects:
            entity_name = f"{row['schema_name']}.{row['object_name']}"
            if not self._policy.allows_entity(entity_name):
                continue
            fields = []
            primary_key = primary_by_entity.get(entity_name, [])
            for column in columns_by_entity.get(entity_name, []):
                field_name = column["field_name"]
                if not self._policy.allows_field(entity_name, field_name):
                    continue
                data_type = column["data_type"]
                if data_type in {"json", "jsonb", "bytea"}:
                    continue
                fields.append(
                    FieldInfo(
                        name=field_name,
                        data_type=data_type,
                        nullable=column["nullable"],
                        ordinal_position=column["ordinal_position"],
                        description=self._policy.field_description(
                            entity_name, field_name, column.get("description")
                        ),
                        is_primary_key=field_name in primary_key,
                        is_indexed=(entity_name, field_name) in indexed,
                        is_numeric=data_type in _NUMERIC_TYPES,
                        is_text=data_type in _TEXT_TYPES,
                        enum_values=self._policy.enum_values(entity_name, field_name),
                    )
                )
            allowed_names = {field.name for field in fields}
            if not allowed_names:
                continue
            allowed_primary_key = primary_key if set(primary_key).issubset(allowed_names) else []
            summary = EntitySummary(
                name=entity_name,
                schema_name=row["schema_name"],
                object_name=row["object_name"],
                kind=_KIND_MAP[row["relkind"]],
                description=self._policy.entity_description(entity_name, row.get("description")),
                aliases=self._policy.aliases(entity_name),
                estimated_rows=max(0, int(row["estimated_rows"]))
                if row["estimated_rows"] is not None
                else None,
            )
            entities[entity_name] = EntityInfo(
                **summary.model_dump(),
                fields=fields,
                primary_key=allowed_primary_key,
                relations=[],
            )

        self._attach_relations(entities, foreign_keys)
        fingerprint = self._fingerprint(entities)
        return CatalogSnapshot(
            entities=entities,
            fingerprint=fingerprint,
            loaded_at=datetime.now(UTC),
        )

    async def _fetch_objects(self, connection: Any) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS object_name,
                   c.relkind,
                   obj_description(c.oid, 'pg_class') AS description,
                   c.reltuples::bigint AS estimated_rows
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ANY(%s)
              AND c.relkind = ANY(ARRAY['r','v','m','p','f']::"char"[])
              AND has_table_privilege(c.oid, 'SELECT')
            ORDER BY n.nspname, c.relname
            """,
            (self._policy.schemas,),
        )
        return list(await cursor.fetchall())

    async def _fetch_columns(self, connection: Any) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT n.nspname AS schema_name, c.relname AS object_name,
                   a.attname AS field_name, format_type(a.atttypid, NULL) AS data_type,
                   NOT a.attnotnull AS nullable, a.attnum AS ordinal_position,
                   col_description(c.oid, a.attnum) AS description
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped
              AND c.relkind = ANY(ARRAY['r','v','m','p','f']::"char"[])
              AND has_column_privilege(c.oid,a.attnum,'SELECT')
            ORDER BY n.nspname,c.relname,a.attnum
            """,
            (self._policy.schemas,),
        )
        return list(await cursor.fetchall())

    async def _fetch_primary_keys(self, connection: Any) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS object_name,
                   a.attname AS field_name
            FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_class c ON c.oid = i.indrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS keys(attnum, ord)
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = keys.attnum
            WHERE i.indisprimary
              AND n.nspname = ANY(%s)
            ORDER BY n.nspname, c.relname, keys.ord
            """,
            (self._policy.schemas,),
        )
        return list(await cursor.fetchall())

    async def _fetch_foreign_keys(self, connection: Any) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT con.conname AS relation_name,
                   src_ns.nspname AS source_schema,
                   src.relname AS source_object,
                   array_agg(src_att.attname ORDER BY key_map.ord) AS source_fields,
                   dst_ns.nspname AS target_schema,
                   dst.relname AS target_object,
                   array_agg(dst_att.attname ORDER BY key_map.ord) AS target_fields
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class src ON src.oid = con.conrelid
            JOIN pg_catalog.pg_namespace src_ns ON src_ns.oid = src.relnamespace
            JOIN pg_catalog.pg_class dst ON dst.oid = con.confrelid
            JOIN pg_catalog.pg_namespace dst_ns ON dst_ns.oid = dst.relnamespace
            CROSS JOIN LATERAL unnest(con.conkey, con.confkey)
                WITH ORDINALITY AS key_map(src_attnum, dst_attnum, ord)
            JOIN pg_catalog.pg_attribute src_att
                ON src_att.attrelid = src.oid AND src_att.attnum = key_map.src_attnum
            JOIN pg_catalog.pg_attribute dst_att
                ON dst_att.attrelid = dst.oid AND dst_att.attnum = key_map.dst_attnum
            WHERE con.contype = 'f'
              AND src_ns.nspname = ANY(%s)
              AND dst_ns.nspname = ANY(%s)
            GROUP BY con.conname, src_ns.nspname, src.relname, dst_ns.nspname, dst.relname
            ORDER BY src_ns.nspname, src.relname, con.conname
            """,
            (self._policy.schemas, self._policy.schemas),
        )
        return list(await cursor.fetchall())

    async def _fetch_indexed_fields(self, connection: Any) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT DISTINCT n.nspname AS schema_name,
                   c.relname AS object_name,
                   a.attname AS field_name
            FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_class c ON c.oid = i.indrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN LATERAL unnest(i.indkey) AS keys(attnum)
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = keys.attnum
            WHERE n.nspname = ANY(%s)
              AND keys.attnum > 0
            """,
            (self._policy.schemas,),
        )
        return list(await cursor.fetchall())

    def _attach_relations(
        self,
        entities: dict[str, EntityInfo],
        rows: list[dict[str, Any]],
    ) -> None:
        for row in rows:
            source = f"{row['source_schema']}.{row['source_object']}"
            target = f"{row['target_schema']}.{row['target_object']}"
            if source not in entities or target not in entities:
                continue
            source_fields = list(row["source_fields"])
            target_fields = list(row["target_fields"])
            source_allowed = {field.name for field in entities[source].fields}
            target_allowed = {field.name for field in entities[target].fields}
            if not set(source_fields).issubset(source_allowed) or not set(target_fields).issubset(
                target_allowed
            ):
                continue
            base_name = str(row["relation_name"])
            entities[source].relations.append(
                RelationInfo(
                    name=f"{base_name}:outbound",
                    source_entity=source,
                    source_fields=source_fields,
                    target_entity=target,
                    target_fields=target_fields,
                    direction=RelationDirection.OUTBOUND,
                )
            )
            entities[target].relations.append(
                RelationInfo(
                    name=f"{base_name}:inbound",
                    source_entity=source,
                    source_fields=source_fields,
                    target_entity=target,
                    target_fields=target_fields,
                    direction=RelationDirection.INBOUND,
                )
            )

    @staticmethod
    def _fingerprint(entities: dict[str, EntityInfo]) -> str:
        payload = {
            name: {
                "kind": entity.kind.value,
                "fields": [
                    (field.name, field.data_type, field.nullable) for field in entity.fields
                ],
                "primary_key": entity.primary_key,
                "relations": [
                    (
                        relation.name,
                        relation.source_entity,
                        relation.source_fields,
                        relation.target_entity,
                        relation.target_fields,
                    )
                    for relation in entity.relations
                ],
            }
            for name, entity in sorted(entities.items())
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
