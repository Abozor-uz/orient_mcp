# app/presentation/mcp/server.py
# ============================================================================
# Orient MCP Tool Surface
#
# Exposes authenticated structured reads with explicit source selection.
# Business services enforce field policies, bounded queries and provenance.
# ============================================================================

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from psycopg import OperationalError, errors
from psycopg_pool import PoolTimeout
from pydantic import AnyHttpUrl

from app.domain.auth import RequestIdentity
from app.domain.customer_lookup import CustomerQuery, VehicleQuery
from app.domain.errors import CatalogError, QueryValidationError
from app.domain.models import AggregateMetric, EntityKind, FilterSpec, SortSpec, ToolResult
from app.logging_config import logger
from app.presentation.mcp.tool_views import ToolViews

if TYPE_CHECKING:
    from app.bootstrap.dependencies import ApplicationDependencies

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)


def build_fastmcp(deps: ApplicationDependencies) -> FastMCP:
    views = ToolViews()
    host = urlparse(deps.settings.public_base_url).netloc
    mcp = FastMCP(
        name=views.text("name"),
        instructions=views.text("instructions"),
        json_response=True,
        stateless_http=True,
        streamable_http_path="/mcp",
        token_verifier=deps.token_verifier,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[host],
            allowed_origins=deps.settings.allowed_origins,
        ),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(deps.settings.public_base_url),
            resource_server_url=AnyHttpUrl(deps.settings.resource),
            required_scopes=["orient:read"],
        ),
    )
    _register_tools(mcp, deps, views)
    return mcp


def _register_tools(mcp: FastMCP, deps: ApplicationDependencies, views: ToolViews) -> None:
    @mcp.tool(description=views.text("search_customers"), annotations=_READ_ONLY)
    async def search_customers(
        phone: str | None = None,
        customer_id: int | None = None,
        limit: int = 20,
        after_id: int = 0,
        source: str | None = None,
    ) -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            selected = deps.resolve_source(source)
            page = await selected.customer_lookup_service.customers(
                CustomerQuery(
                    phone=phone,
                    customer_id=customer_id,
                    limit=limit,
                    after_id=after_id,
                )
            )
            return _result(
                views, "records_loaded", page, selected.name, len(page.customers), page.has_more
            )

        return await _run(deps, "search_customers", source, "public.users", execute)

    @mcp.tool(description=views.text("search_vehicles"), annotations=_READ_ONLY)
    async def search_vehicles(
        plate_number: str | None = None,
        vin: str | None = None,
        customer_id: int | None = None,
        limit: int = 20,
        after_id: int = 0,
        source: str | None = None,
    ) -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            selected = deps.resolve_source(source)
            page = await selected.customer_lookup_service.vehicles(
                VehicleQuery(
                    plate_number=plate_number,
                    vin=vin,
                    customer_id=customer_id,
                    limit=limit,
                    after_id=after_id,
                )
            )
            return _result(
                views, "records_loaded", page, selected.name, len(page.vehicles), page.has_more
            )

        return await _run(
            deps, "search_vehicles", source, "public.business_account_garagecar", execute
        )

    @mcp.tool(description=views.text("list_sources"), annotations=_READ_ONLY)
    async def list_sources() -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            names = list(deps.sources)
            return _result(views, "sources_loaded", names, "orient-mcp", len(names))

        return await _run(deps, "list_sources", None, None, execute)

    @mcp.tool(description=views.text("get_current_context"), annotations=_READ_ONLY)
    async def get_current_context(source: str | None = None) -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            selected = deps.resolve_source(source)
            context = await selected.context_service.get_context()
            return _result(views, "context_loaded", context, selected.name, 1)

        return await _run(deps, "get_current_context", source, None, execute)

    @mcp.tool(description=views.text("list_entities"), annotations=_READ_ONLY)
    async def list_entities(
        query: str | None = None,
        kind: EntityKind | None = None,
        limit: int = 50,
        offset: int = 0,
        source: str | None = None,
    ) -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            selected = deps.resolve_source(source)
            deps.validator.validate_limit(limit)
            if not 0 <= offset <= 10000:
                raise QueryValidationError("invalid_offset")
            entities, snapshot = await selected.catalog_service.list_entities(
                query=query,
                kind=kind,
                limit=limit + 1,
                offset=offset,
            )
            more = len(entities) > limit
            data = {
                "entities": entities[:limit],
                "has_more": more,
                "next_offset": offset + limit if more else None,
                "schema_fingerprint": snapshot.fingerprint,
            }
            return _result(views, "entities_loaded", data, selected.name, min(len(entities), limit))

        return await _run(deps, "list_entities", source, None, execute)

    @mcp.tool(description=views.text("get_entity_fields"), annotations=_READ_ONLY)
    async def get_entity_fields(entity: str, source: str | None = None) -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            selected = deps.resolve_source(source)
            info, _ = await selected.catalog_service.get_entity(entity)
            return _result(views, "fields_loaded", info, selected.name, len(info.fields))

        return await _run(deps, "get_entity_fields", source, entity, execute)

    @mcp.tool(description=views.text("search_records"), annotations=_READ_ONLY)
    async def search_records(
        entity: str,
        fields: list[str],
        filters: list[FilterSpec] | None = None,
        order_by: list[SortSpec] | None = None,
        limit: int = 20,
        cursor: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            selected = deps.resolve_source(source)
            page = await selected.record_service.search(
                entity_name=entity,
                fields=fields,
                filters=filters or [],
                order_by=order_by or [],
                limit=limit,
                cursor=cursor,
            )
            return _result(
                views, "records_loaded", page, selected.name, page.row_count, page.has_more
            )

        return await _run(deps, "search_records", source, entity, execute)

    @mcp.tool(description=views.text("get_record"), annotations=_READ_ONLY)
    async def get_record(
        entity: str,
        key: dict[str, Any],
        fields: list[str],
        source: str | None = None,
    ) -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            selected = deps.resolve_source(source)
            record = await selected.record_service.get_one(
                entity_name=entity, key=key, fields=fields
            )
            if record is None:
                raise QueryValidationError("record_not_found_or_not_unique")
            return _result(views, "records_loaded", record, selected.name, 1)

        return await _run(deps, "get_record", source, entity, execute)

    @mcp.tool(description=views.text("aggregate_records"), annotations=_READ_ONLY)
    async def aggregate_records(
        entity: str,
        metrics: list[AggregateMetric],
        group_by: list[str] | None = None,
        filters: list[FilterSpec] | None = None,
        limit: int = 100,
        source: str | None = None,
    ) -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            selected = deps.resolve_source(source)
            result = await selected.aggregation_service.aggregate(
                entity_name=entity,
                metrics=metrics,
                group_by=group_by or [],
                filters=filters or [],
                limit=limit,
            )
            return _result(
                views,
                "aggregates_loaded",
                result,
                selected.name,
                result.row_count,
                result.truncated,
            )

        return await _run(deps, "aggregate_records", source, entity, execute)

    @mcp.tool(description=views.text("get_related_records"), annotations=_READ_ONLY)
    async def get_related_records(
        entity: str,
        key: dict[str, Any],
        relation: str,
        fields: list[str],
        limit: int = 20,
        cursor: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        async def execute() -> ToolResult[Any]:
            selected = deps.resolve_source(source)
            page = await selected.relation_service.related(
                entity_name=entity,
                key=key,
                relation_name=relation,
                fields=fields,
                limit=limit,
                cursor=cursor,
            )
            return _result(
                views, "records_loaded", page, selected.name, page.row_count, page.has_more
            )

        return await _run(deps, "get_related_records", source, entity, execute)


def _result(
    views: ToolViews,
    key: str,
    data: Any,
    source: str,
    count: int,
    truncated: bool = False,
) -> ToolResult[Any]:
    return ToolResult(
        summary=views.text(key),
        data=data,
        source=source,
        as_of=datetime.now(UTC),
        count=count,
        warnings=[views.text("truncated")] if truncated else [],
    )


async def _run(
    deps: ApplicationDependencies,
    tool: str,
    source: str | None,
    entity: str | None,
    operation: Callable[[], Awaitable[ToolResult[Any]]],
) -> dict[str, Any]:
    token = get_access_token()
    if token is None:
        raise ValueError("authentication_required")
    identity = RequestIdentity(
        principal_id=token.subject or "unknown",
        principal_login=deps.settings.mcp_agent_login,
        client_id=token.client_id,
        token_family_id=(token.claims or {}).get("token_family_id"),
        scope=" ".join(token.scopes),
        resource=deps.settings.resource,
    )
    audit_entity = f"{source or deps.settings.data_source_label}:{entity or ''}"[:255]
    try:
        async with deps.audit_service.operation(identity, tool, audit_entity) as audit:
            result = await operation()
            audit["result_count"] = result.count or 0
            payload = result.model_dump(mode="json")
            if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 1_048_576:
                raise QueryValidationError("response_too_large_narrow_fields_or_filters")
            return payload
    except (CatalogError, QueryValidationError) as exc:
        raise ValueError(exc.code) from None
    except errors.QueryCanceled:
        raise ValueError("query_timeout") from None
    except (OperationalError, PoolTimeout):
        raise ValueError("database_temporarily_unavailable") from None
    except Exception as exc:
        logger.warning("mcp tool failed", extra={"tool": tool, "error_type": type(exc).__name__})
        raise ValueError("internal_error") from None
