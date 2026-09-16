# tests/integration/test_http_oauth.py
# ============================================================================
# OAuth and MCP HTTP Acceptance
#
# Tests the complete HTTP authentication and tool path with real PostgreSQL
# control state. No repositories or external interfaces are mocked.
# ============================================================================

from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import parse_qs, urlparse

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings


async def test_oauth_pkce_tools_refresh_and_revocation(integration_settings: Settings) -> None:
    application = create_app(integration_settings)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://localhost:8000"
        ) as client:
            ready = await client.get("/health/ready")
            assert ready.status_code == 200
            assert ready.json()["read_only"] is True
            assert len(ready.json()["sources"]) == 2
            headers = {"Accept": "application/json, text/event-stream"}
            rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            unauthenticated = await client.post("/mcp", json=rpc, headers=headers)
            assert unauthenticated.status_code == 401
            registration = await client.post(
                "/mcp/oauth/register",
                json={
                    "client_name": "Local acceptance",
                    "redirect_uris": ["https://chatgpt.com/aip/callback"],
                    "scope": "orient:read offline_access",
                },
            )
            assert registration.status_code == 201
            client_id = registration.json()["client_id"]
            verifier = "x" * 64
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            authorize = await client.get(
                "/mcp/oauth/authorize",
                params={
                    "client_id": client_id,
                    "redirect_uri": "https://chatgpt.com/aip/callback",
                    "response_type": "code",
                    "scope": "orient:read offline_access",
                    "state": "local-state",
                    "resource": integration_settings.resource,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
            )
            assert authorize.status_code == 200
            request_id = re.search(r'name="request_id" value="([^"]+)"', authorize.text).group(1)
            login = await client.post(
                "/mcp/oauth/authorize",
                data={
                    "request_id": request_id,
                    "login": integration_settings.mcp_agent_login,
                    "password": "local-test-password",
                },
            )
            assert login.status_code == 302
            callback = parse_qs(urlparse(login.headers["location"]).query)
            assert callback["state"] == ["local-state"]
            token_data = {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": callback["code"][0],
                "redirect_uri": "https://chatgpt.com/aip/callback",
                "code_verifier": verifier,
                "resource": integration_settings.resource,
            }
            token = await client.post("/mcp/oauth/token", data=token_data)
            assert token.status_code == 200
            assert (await client.post("/mcp/oauth/token", data=token_data)).status_code == 400
            tokens = token.json()
            headers["Authorization"] = "Bearer " + tokens["access_token"]
            listed = await client.post("/mcp", json=rpc, headers=headers)
            assert listed.status_code == 200
            assert len(listed.json()["result"]["tools"]) == 10
            tool = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "search_records",
                        "arguments": {
                            "entity": "public.users",
                            "fields": ["id", "username"],
                            "limit": 1,
                        },
                    },
                },
            )
            assert tool.status_code == 200
            result = tool.json()["result"]
            assert not result.get("isError"), result
            assert result["structuredContent"]["data"]["row_count"] == 1
            for name, arguments, collection in [
                ("search_customers", {"phone": "+998 (90) 123-45-67"}, "customers"),
                ("search_vehicles", {"plate_number": "01 a 123 bc"}, "vehicles"),
                ("search_vehicles", {"vin": "1hgcm82633a004352"}, "vehicles"),
            ]:
                lookup = await client.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    },
                )
                lookup_result = lookup.json()["result"]
                assert not lookup_result.get("isError"), lookup_result
                assert lookup_result["structuredContent"]["data"][collection]
            for entity, field in [
                ("public.users", "password"),
                ("public.business_account_garagecar", "pinpp"),
                ("public.business_account_garagecar", "prev_pnfl"),
                ("public.business_account_garagecar", "extra_data"),
            ]:
                forbidden = await client.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "search_records",
                            "arguments": {"entity": entity, "fields": [field]},
                        },
                    },
                )
                assert forbidden.json()["result"]["isError"] is True
                assert "field_not_allowed" in forbidden.text
            refreshed = await client.post(
                "/mcp/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": tokens["refresh_token"],
                    "resource": integration_settings.resource,
                },
            )
            assert refreshed.status_code == 200
            new_access = refreshed.json()["access_token"]
            assert (
                await client.post("/mcp/oauth/revoke", data={"token": new_access})
            ).status_code == 200
            headers["Authorization"] = "Bearer " + new_access
            assert (await client.post("/mcp", json=rpc, headers=headers)).status_code == 401
