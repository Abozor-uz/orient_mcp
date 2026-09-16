# app/main.py
# ============================================================================
# Orient MCP FastAPI Entry Point
#
# Creates the production application, binds OAuth and MCP routes, and exposes
# separate liveness and database-backed readiness checks for Render.
# ============================================================================

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.bootstrap.dependencies import ApplicationDependencies, build_dependencies
from app.logging_config import configure_logging, logger
from app.presentation.body_limit import BodyLimitMiddleware
from app.presentation.mcp.runtime import McpRuntime
from app.settings import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    dependencies: ApplicationDependencies | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    deps = dependencies or build_dependencies(resolved_settings)
    runtime = McpRuntime(deps)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await deps.start()
        try:
            await runtime.start()
            yield
        finally:
            await runtime.stop()
            await deps.stop()

    application = FastAPI(
        title="Orient MCP",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if resolved_settings.environment == "production" else "/docs",
        redoc_url=None,
    )
    application.include_router(runtime.oauth_router())
    application.add_middleware(
        BodyLimitMiddleware, max_bytes=resolved_settings.mcp_max_request_bytes
    )
    runtime.mount(application)
    application.state.dependencies = deps

    @application.get("/health/live", tags=["health"])
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready", tags=["health"])
    async def health_ready() -> JSONResponse:
        try:
            contexts = [
                await source.context_service.get_context() for source in deps.sources.values()
            ]
            principal = await deps.control_store.get_active_principal(
                resolved_settings.mcp_agent_login
            )
            if principal is None:
                raise RuntimeError("principal_unavailable")
            return JSONResponse(
                {
                    "status": "ready",
                    "read_only": all(context.transaction_read_only for context in contexts),
                    "sources": [
                        {
                            "source": context.source,
                            "schema_fingerprint": context.schema_fingerprint,
                            "entity_count": context.entity_count,
                        }
                        for context in contexts
                    ],
                }
            )
        except Exception as exc:
            logger.warning(
                "readiness check failed",
                extra={"error_type": type(exc).__name__},
            )
            return JSONResponse({"status": "not_ready"}, status_code=503)

    return application
