# app/gateway_stdio.py
# ============================================================================
# Gateway-Owned Orient MCP Transport
#
# Reuses the HTTP reader and all existing tools over the Gateway's private
# stdio channel. Gateway owns authentication, access rules and activity logs;
# this process never opens the legacy OAuth/control database.
# ============================================================================
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP
from psycopg import OperationalError, errors
from psycopg_pool import PoolTimeout

from app.bootstrap.dependencies import ApplicationDependencies, build_dependencies
from app.domain.errors import OrientMcpError
from app.logging_config import configure_logging, logger
from app.presentation.mcp.server import ToolOperation, _register_tools
from app.presentation.mcp.tool_views import ToolViews
from app.settings import Settings, get_settings


async def _run_gateway(
    deps: ApplicationDependencies,
    tool: str,
    source: str | None,
    entity: str | None,
    operation: ToolOperation,
) -> dict[str, Any]:
    try:
        result = await operation()
        payload = result.model_dump(mode="json")
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 1_048_576:
            raise ValueError("response_too_large_narrow_fields_or_filters")
        logger.info("gateway read completed", extra={"tool": tool, "row_count": result.count})
        return payload
    except OrientMcpError as error:
        raise ValueError(error.code) from None
    except errors.QueryCanceled:
        raise ValueError("query_timeout") from None
    except (OperationalError, PoolTimeout):
        raise ValueError("database_temporarily_unavailable") from None
    except ValueError:
        raise
    except Exception as error:
        logger.warning(
            "gateway read failed", extra={"tool": tool, "error_type": type(error).__name__}
        )
        raise ValueError("internal_error") from None


def build_gateway_mcp(settings: Settings) -> tuple[FastMCP, ApplicationDependencies]:
    if settings.orient_source_transport != "http":
        raise ValueError("gateway_primary_source_must_use_http")
    deps = build_dependencies(settings)

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[None]:
        try:
            for selected in deps.sources.values():
                await selected.data_pool.open()
            yield None
        finally:
            for selected in deps.sources.values():
                await selected.data_pool.close()

    views = ToolViews()
    server = FastMCP(
        name=views.text("name"), instructions=views.text("instructions"), lifespan=lifespan
    )
    _register_tools(server, deps, views, operation_runner=_run_gateway)
    return server, deps


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    server, _ = build_gateway_mcp(settings)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
