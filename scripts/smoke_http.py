# scripts/smoke_http.py
# ============================================================================
# Deployed MCP Smoke Check
#
# Uses an existing access token to check readiness, tool discovery and source
# context. It never writes source data or retrieves business rows.
# ============================================================================

from __future__ import annotations

import json
import os

import httpx


def main() -> None:
    base = os.environ["MCP_PUBLIC_BASE_URL"].rstrip("/")
    token = os.environ["MCP_SMOKE_ACCESS_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    with httpx.Client(base_url=base, timeout=30, headers=headers) as client:
        ready = client.get("/health/ready")
        ready.raise_for_status()
        assert ready.json()["read_only"] is True
        for index, (method, params) in enumerate(
            [
                (
                    "initialize",
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "orient-smoke", "version": "1"},
                    },
                ),
                ("tools/list", {}),
                ("tools/call", {"name": "list_sources", "arguments": {}}),
                ("tools/call", {"name": "get_current_context", "arguments": {}}),
            ],
            1,
        ):
            response = client.post(
                "/mcp", json={"jsonrpc": "2.0", "id": index, "method": method, "params": params}
            )
            response.raise_for_status()
            payload = response.json()
            if "error" in payload or payload.get("result", {}).get("isError"):
                raise RuntimeError("mcp_smoke_failed")
            if method == "initialize":
                client.headers["MCP-Protocol-Version"] = payload["result"]["protocolVersion"]
                client.post(
                    "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
                ).raise_for_status()
            print(json.dumps({"check": method, "status": "ok"}))


if __name__ == "__main__":
    main()
