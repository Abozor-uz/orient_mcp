# tests/unit/test_mcp_contract.py
# ============================================================================
# MCP Server Contract Tests
#
# Verifies the production SDK can build the server and exposes only read tools.
# ============================================================================

from __future__ import annotations

from app.bootstrap.dependencies import build_dependencies
from app.presentation.mcp.server import build_fastmcp
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        orient_database_url="postgresql://reader:secret@localhost/orient",
        mcp_control_database_url="postgresql://control:secret@localhost/control",
        mcp_public_base_url="https://mcp.example.com",
        mcp_agent_password_hash="$2b$12$placeholder",
        mcp_auth_pepper="0123456789abcdef",
        mcp_allowed_origins="https://chatgpt.com",
        mcp_allowed_redirect_origins="https://chatgpt.com",
    )


async def test_mcp_exposes_exact_read_only_tool_contract() -> None:
    server = build_fastmcp(build_dependencies(_settings()))

    tools = await server.list_tools()
    names = {tool.name for tool in tools}

    assert names == {
        "list_sources",
        "get_current_context",
        "list_entities",
        "get_entity_fields",
        "search_records",
        "search_customers",
        "search_vehicles",
        "get_record",
        "aggregate_records",
        "get_related_records",
    }
    assert all(tool.annotations and tool.annotations.readOnlyHint for tool in tools)
    assert all(tool.annotations and tool.annotations.idempotentHint for tool in tools)
    assert not any(name.startswith(("create_", "update_", "delete_", "execute_")) for name in names)
