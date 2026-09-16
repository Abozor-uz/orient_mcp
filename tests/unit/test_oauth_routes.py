# tests/unit/test_oauth_routes.py
# ============================================================================
# OAuth HTTP Contract Tests
#
# Confirms discovery metadata matches the deployed resource and PKCE endpoints.
# ============================================================================

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.presentation.mcp.oauth_routes import _language, create_oauth_router
from app.presentation.mcp.views import OAuthViews
from app.services.auth_service import OAuthService, PrincipalService
from app.services.security_service import SecurityService


async def test_oauth_discovery_advertises_pkce_and_registration() -> None:
    app = FastAPI()
    app.include_router(
        create_oauth_router(
            oauth=cast(OAuthService, cast(Any, object())),
            principals=cast(PrincipalService, cast(Any, object())),
            security=cast(SecurityService, cast(Any, object())),
            views=OAuthViews(),
            base_url="https://mcp.example.com",
            resource="https://mcp.example.com/mcp",
            max_request_bytes=1024,
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        protected = await client.get("/.well-known/oauth-protected-resource/mcp")
        authorization = await client.get("/.well-known/oauth-authorization-server")

    assert protected.status_code == 200
    assert protected.json()["resource"] == "https://mcp.example.com/mcp"
    assert authorization.json()["registration_endpoint"].endswith("/mcp/oauth/register")
    assert authorization.json()["code_challenge_methods_supported"] == ["S256"]


def test_oauth_language_defaults_when_ui_locales_is_missing() -> None:
    assert _language(None) == "ru"
    assert _language("") == "ru"
    assert _language("uz-UZ ru-RU") == "uz"
