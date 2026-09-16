# app/presentation/mcp/runtime.py
# ============================================================================
# MCP Runtime Lifecycle
#
# Mounts the exact /mcp transport route with bearer middleware and owns the SDK
# session manager plus periodic control-store maintenance.
# ============================================================================

from __future__ import annotations

from contextlib import AsyncExitStack

from fastapi import APIRouter, FastAPI

from app.bootstrap.dependencies import ApplicationDependencies
from app.presentation.mcp.oauth_routes import create_oauth_router
from app.presentation.mcp.server import build_fastmcp
from app.services.maintenance_service import MaintenanceScheduler


class McpRuntime:
    def __init__(self, deps: ApplicationDependencies) -> None:
        self._deps = deps
        self._fastmcp = build_fastmcp(deps)
        self._asgi_app = self._fastmcp.streamable_http_app()
        self._stack: AsyncExitStack | None = None
        self._maintenance = MaintenanceScheduler(
            deps.maintenance_service,
            deps.settings.mcp_cleanup_interval_hours,
        )

    def oauth_router(self) -> APIRouter:
        return create_oauth_router(
            oauth=self._deps.oauth_service,
            principals=self._deps.principal_service,
            security=self._deps.security_service,
            views=self._deps.oauth_views,
            base_url=self._deps.settings.public_base_url,
            resource=self._deps.settings.resource,
            max_request_bytes=self._deps.settings.mcp_max_request_bytes,
        )

    def mount(self, app: FastAPI) -> None:
        from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
        from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
        from starlette.middleware.authentication import AuthenticationMiddleware
        from starlette.routing import Route

        for route in self._asgi_app.routes:
            if isinstance(route, Route) and route.path == "/mcp":
                route.app = AuthenticationMiddleware(
                    AuthContextMiddleware(route.app),
                    backend=BearerAuthBackend(self._deps.token_verifier),
                )
                app.router.routes.append(route)
                return
        raise RuntimeError("mcp_transport_route_missing")

    async def start(self) -> None:
        if self._stack is not None:
            return
        self._stack = AsyncExitStack()
        await self._stack.enter_async_context(self._fastmcp.session_manager.run())
        self._maintenance.start()

    async def stop(self) -> None:
        await self._maintenance.stop()
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
