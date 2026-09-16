# app/bootstrap/sources.py
# ============================================================================
# Source Dependency Composition
#
# Builds isolated catalogs and bounded read pools for configured databases.
# Source names are deployment configuration, never arbitrary connection input.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass

from psycopg.conninfo import make_conninfo

from app.infrastructure.policy import CatalogPolicy
from app.infrastructure.postgres.catalog_repository import PostgresCatalogRepository
from app.infrastructure.postgres.customer_lookup_repository import PostgresCustomerLookupRepository
from app.infrastructure.postgres.pool import PostgresPool
from app.infrastructure.postgres.record_repository import PostgresRecordRepository
from app.services.catalog_service import CatalogService
from app.services.cursor_service import CursorCodec
from app.services.customer_lookup_service import CustomerLookupService
from app.services.read_services import (
    AggregationService,
    ContextService,
    RecordSearchService,
    RelationService,
)
from app.services.validation_service import QueryValidationService
from app.settings import Settings


@dataclass(slots=True)
class SourceDependencies:
    name: str
    data_pool: PostgresPool
    catalog_service: CatalogService
    record_service: RecordSearchService
    aggregation_service: AggregationService
    relation_service: RelationService
    context_service: ContextService
    customer_lookup_service: CustomerLookupService


def build_source(settings: Settings, name: str, database: str | None = None) -> SourceDependencies:
    url = settings.orient_database_url.get_secret_value()
    if database is not None:
        url = make_conninfo(url, dbname=database)
    pool = PostgresPool(
        connection_url=url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        statement_timeout_ms=settings.db_statement_timeout_ms,
        lock_timeout_ms=settings.db_lock_timeout_ms,
        idle_transaction_timeout_ms=settings.db_idle_transaction_timeout_ms,
        read_only=True,
        read_role=settings.orient_read_role or None,
    )
    policy = CatalogPolicy.load(settings.orient_policy_path, settings.allowed_schemas)
    repository = PostgresRecordRepository(pool)
    catalog = CatalogService(PostgresCatalogRepository(pool, policy), settings.catalog_ttl_seconds)
    validator = QueryValidationService()
    # A cursor from an identically shaped database must never cross source boundaries.
    cursors = CursorCodec(settings.mcp_auth_pepper.get_secret_value() + ":" + name)
    return SourceDependencies(
        name=name,
        data_pool=pool,
        catalog_service=catalog,
        record_service=RecordSearchService(catalog, repository, validator, cursors),
        aggregation_service=AggregationService(catalog, repository, validator),
        relation_service=RelationService(catalog, repository, validator, cursors),
        context_service=ContextService(catalog, repository, name),
        customer_lookup_service=CustomerLookupService(
            catalog, PostgresCustomerLookupRepository(pool)
        ),
    )
