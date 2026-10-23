# tests/unit/test_source_transport.py
# ============================================================================
# Source Transport Selection
#
# Keeps the primary Orient HTTP reader isolated from additional databases and
# the existing writable control store.
# ============================================================================
from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from app.bootstrap.dependencies import build_dependencies
from app.domain.errors import DataSourceUnavailableError
from app.infrastructure.http.source_client import OrientSourceHttpClient
from app.infrastructure.postgres.pool import PostgresPool
from app.settings import Settings


def configuration(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "development",
        "orient_source_transport": "http",
        "orient_api_service_key": "synthetic-key",
        "orient_database_url": "postgresql://reader:test@localhost/orient_test",
        "orient_additional_databases": "garage,notification",
        "mcp_control_database_url": "postgresql://control:test@localhost/control",
        "mcp_public_base_url": "https://mcp.example.com",
        "mcp_agent_password_hash": "$2b$12$placeholder",
        "mcp_auth_pepper": "0123456789abcdef",
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


async def test_http_primary_preserves_additional_sources_and_control_store() -> None:
    dependencies = build_dependencies(configuration())
    try:
        assert isinstance(dependencies.data_pool, OrientSourceHttpClient)
        assert dependencies.data_pool.expected_database == "orient_test"
        assert dependencies.data_pool.base_url == "https://motors.itpoint.uz"
        assert isinstance(dependencies.sources["garage"].data_pool, PostgresPool)
        assert isinstance(dependencies.sources["notification"].data_pool, PostgresPool)
        assert isinstance(dependencies.control_pool, PostgresPool)
    finally:
        await dependencies.stop()


def test_http_additional_sources_still_require_their_existing_database_connection() -> None:
    with pytest.raises(ValidationError, match="additional_database_connection_required"):
        configuration(orient_database_url=None)


def test_production_additional_sources_keep_tls_validation() -> None:
    with pytest.raises(ValidationError, match="production_database_tls_required"):
        configuration(
            environment="production",
            mcp_control_database_url="postgresql://control:test@localhost/control?sslmode=require",
        )


@pytest.mark.parametrize("scenario", ["unavailable", "wrong_database", "wrong_environment"])
async def test_http_source_failures_never_open_a_postgres_fallback(scenario: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Api-Key"] == "synthetic-key"
        if scenario == "unavailable":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "contract_version": 1,
                "environment": "dev" if scenario == "wrong_environment" else "production",
                "source": "orient",
                "action": "context",
                "source_database": "other" if scenario == "wrong_database" else "orient_test",
                "payload": {},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = OrientSourceHttpClient(
            base_url="https://motors.itpoint.uz",
            service_key="synthetic-key",
            source="orient",
            environment="production",
            expected_database="orient_test",
            http_client=http,
        )
        with pytest.raises(DataSourceUnavailableError):
            await client.read("context")
