# tests/unit/test_oauth_service.py
# ============================================================================
# OAuth Service Tests
#
# Covers dynamic client registration, redirect boundaries, and PKCE requests.
# ============================================================================

from __future__ import annotations

from typing import cast

import pytest

from app.domain.auth import AuthorizationRequest, OAuthClient
from app.domain.auth_ports import ControlStorePort
from app.services.auth_service import OAuthError, OAuthService


class OAuthStoreStub:
    def __init__(self) -> None:
        self.clients: dict[str, OAuthClient] = {}
        self.requests: dict[str, AuthorizationRequest] = {}

    async def create_client(self, client: OAuthClient) -> OAuthClient:
        self.clients[client.client_id] = client
        return client

    async def get_client(self, client_id: str) -> OAuthClient | None:
        return self.clients.get(client_id)

    async def create_request(self, request: AuthorizationRequest) -> AuthorizationRequest:
        self.requests[request.request_hash] = request
        return request


def _service(store: OAuthStoreStub) -> OAuthService:
    return OAuthService(
        cast(ControlStorePort, store),
        public_base_url="https://mcp.example.com",
        principal_login="agent",
        access_ttl_seconds=3600,
        refresh_ttl_days=30,
        code_ttl_seconds=300,
        request_ttl_seconds=600,
        allowed_redirect_origins=["https://chatgpt.com"],
    )


async def test_register_client_and_begin_pkce_authorization() -> None:
    store = OAuthStoreStub()
    service = _service(store)
    client = await service.register_client(
        {
            "client_name": "ChatGPT",
            "redirect_uris": ["https://chatgpt.com/aip/callback"],
            "scope": "orient:read offline_access",
        }
    )

    request_id = await service.begin_authorization(
        client_id=client.client_id,
        redirect_uri=client.redirect_uris[0],
        scope="orient:read offline_access",
        state="state",
        resource="https://mcp.example.com/mcp",
        response_type="code",
        code_challenge="a" * 43,
        code_challenge_method="S256",
    )

    assert request_id
    assert len(store.requests) == 1


async def test_register_client_rejects_unapproved_redirect_origin() -> None:
    with pytest.raises(OAuthError, match="invalid_redirect_uri"):
        await _service(OAuthStoreStub()).register_client(
            {"redirect_uris": ["https://attacker.example/callback"]}
        )
