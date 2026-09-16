# app/bootstrap/dependencies.py
# ============================================================================
# Application Dependency Container
#
# Assembles separate data/control pools, repositories, services, OAuth, audit,
# and token verification without mutable module-level service state.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass

from app.bootstrap.sources import SourceDependencies, build_source
from app.domain.errors import QueryValidationError
from app.infrastructure.postgres.control_repository import PostgresControlRepository
from app.infrastructure.postgres.pool import PostgresPool
from app.presentation.mcp.token_verifier import AccessTokenVerifier
from app.presentation.mcp.views import OAuthViews
from app.services.audit_service import AuditService
from app.services.auth_service import OAuthService, PrincipalService
from app.services.catalog_service import CatalogService
from app.services.maintenance_service import MaintenanceService
from app.services.read_services import (
    AggregationService,
    ContextService,
    RecordSearchService,
    RelationService,
)
from app.services.security_service import SecurityService
from app.services.validation_service import QueryValidationService
from app.settings import Settings


@dataclass(slots=True)
class ApplicationDependencies:
    settings: Settings
    data_pool: PostgresPool
    control_pool: PostgresPool
    control_store: PostgresControlRepository
    catalog_service: CatalogService
    record_service: RecordSearchService
    aggregation_service: AggregationService
    relation_service: RelationService
    context_service: ContextService
    validator: QueryValidationService
    oauth_service: OAuthService
    principal_service: PrincipalService
    security_service: SecurityService
    audit_service: AuditService
    maintenance_service: MaintenanceService
    token_verifier: AccessTokenVerifier
    oauth_views: OAuthViews
    sources: dict[str, SourceDependencies]

    def resolve_source(self, name: str | None) -> SourceDependencies:
        source = self.sources.get(name or self.settings.data_source_label)
        if source is None:
            raise QueryValidationError("source_not_allowed")
        return source

    async def start(self) -> None:
        try:
            await self.control_pool.open()
            await self.control_store.ensure_principal(
                self.settings.mcp_agent_login,
                "Orient Production Analyst",
            )
            for source in self.sources.values():
                await source.data_pool.open()
                await source.context_service.get_context()
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        for source in self.sources.values():
            await source.data_pool.close()
        await self.control_pool.close()


def build_dependencies(settings: Settings) -> ApplicationDependencies:
    primary = build_source(settings, settings.data_source_label)
    sources = {primary.name: primary}
    for database in settings.additional_databases:
        sources[database] = build_source(settings, database, database)
    control_pool = PostgresPool(
        connection_url=settings.mcp_control_database_url.get_secret_value(),
        min_size=1,
        max_size=2,
        statement_timeout_ms=5000,
        lock_timeout_ms=1000,
        idle_transaction_timeout_ms=5000,
        read_only=False,
    )
    control_store = PostgresControlRepository(control_pool)
    validator = QueryValidationService()
    oauth_service = OAuthService(
        control_store,
        public_base_url=settings.public_base_url,
        principal_login=settings.mcp_agent_login,
        access_ttl_seconds=settings.mcp_access_token_ttl_seconds,
        refresh_ttl_days=settings.mcp_refresh_token_ttl_days,
        code_ttl_seconds=settings.mcp_authorization_code_ttl_seconds,
        request_ttl_seconds=settings.mcp_authorization_request_ttl_seconds,
        allowed_redirect_origins=settings.allowed_redirect_origins,
    )
    principal_service = PrincipalService(
        control_store,
        settings.mcp_agent_login,
        settings.mcp_agent_password_hash.get_secret_value(),
    )
    security_service = SecurityService(
        control_store,
        pepper=settings.mcp_auth_pepper.get_secret_value(),
        login_max_failures=settings.mcp_auth_max_failures_per_window,
        register_max_failures=settings.mcp_register_max_failures_per_window,
        window_minutes=settings.mcp_auth_window_minutes,
    )
    audit_service = AuditService(control_store)
    maintenance_service = MaintenanceService(control_store, settings.mcp_audit_retention_days)
    token_verifier = AccessTokenVerifier(
        control_store,
        resource=settings.resource,
        principal_login=settings.mcp_agent_login,
    )
    return ApplicationDependencies(
        settings=settings,
        data_pool=primary.data_pool,
        control_pool=control_pool,
        control_store=control_store,
        catalog_service=primary.catalog_service,
        record_service=primary.record_service,
        aggregation_service=primary.aggregation_service,
        relation_service=primary.relation_service,
        context_service=primary.context_service,
        validator=validator,
        oauth_service=oauth_service,
        principal_service=principal_service,
        security_service=security_service,
        audit_service=audit_service,
        maintenance_service=maintenance_service,
        token_verifier=token_verifier,
        oauth_views=OAuthViews(),
        sources=sources,
    )
