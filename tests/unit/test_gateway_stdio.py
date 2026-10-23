# tests/unit/test_gateway_stdio.py
# ============================================================================
# Gateway Stdio Boundary Tests
#
# Preserves the public tool schemas and keeps the legacy OAuth/control store
# closed while the Gateway uses its own authenticated private stdio channel.
# ============================================================================
from __future__ import annotations

import pytest

from app.bootstrap.dependencies import build_dependencies
from app.gateway_stdio import build_gateway_mcp
from app.infrastructure.http.source_client import OrientSourceHttpClient
from app.presentation.mcp.server import build_fastmcp
from app.settings import Settings


def settings() -> Settings:
    return Settings(
        _env_file=None,
        orient_source_transport="http",
        orient_api_service_key="synthetic-key",
        mcp_control_database_url="postgresql://control:secret@localhost/control",
        mcp_public_base_url="https://mcp.example.com",
        mcp_agent_password_hash="$2b$12$placeholder",
        mcp_auth_pepper="0123456789abcdef",
    )


async def test_gateway_preserves_all_public_tool_schemas_and_read_only_annotations() -> None:
    config = settings()
    gateway, deps = build_gateway_mcp(config)
    standalone_deps = build_dependencies(config)
    standalone = build_fastmcp(standalone_deps)
    try:
        actual = await gateway.list_tools()
        expected = await standalone.list_tools()
        assert len(actual) == 10
        assert [tool.model_dump() for tool in actual] == [tool.model_dump() for tool in expected]
        assert isinstance(deps.data_pool, OrientSourceHttpClient)
        content, structured = await gateway.call_tool("list_sources", {})
        assert content
        assert structured["data"] == ["orient"]
        with pytest.raises(Exception, match="source_not_allowed"):
            await gateway.call_tool("get_current_context", {"source": "unconfigured"})
    finally:
        await deps.stop()
        await standalone_deps.stop()


async def test_gateway_lifespan_never_initializes_legacy_control_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, deps = build_gateway_mcp(settings())

    async def forbidden() -> None:
        raise AssertionError("legacy control storage must remain closed")

    monkeypatch.setattr(deps.control_pool, "open", forbidden)
    async with gateway.settings.lifespan(gateway):
        assert isinstance(deps.data_pool, OrientSourceHttpClient)
    await deps.control_pool.close()


def test_gateway_refuses_a_postgres_primary_source() -> None:
    config = settings().model_copy(update={"orient_source_transport": "postgres"})
    with pytest.raises(ValueError, match="gateway_primary_source_must_use_http"):
        build_gateway_mcp(config)
