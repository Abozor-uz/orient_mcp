# tests/unit/test_settings.py
# ============================================================================
# Settings Contract Tests
#
# Ensures deployment URLs, secrets, and pool bounds fail closed.
# ============================================================================

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "orient_database_url": "postgresql://reader:secret@db/orient",
        "mcp_control_database_url": "postgresql://control:secret@db/control",
        "mcp_public_base_url": "https://mcp.example.com",
        "mcp_agent_password_hash": "$2b$12$placeholder",
        "mcp_auth_pepper": "0123456789abcdef",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_settings_build_exact_resource_url() -> None:
    assert _settings().resource == "https://mcp.example.com/mcp"


def test_settings_reject_non_https_public_origin() -> None:
    with pytest.raises(ValidationError, match="mcp_public_base_url_must_use_https"):
        _settings(mcp_public_base_url="http://mcp.example.com")


def test_settings_reject_invalid_pool_bounds() -> None:
    with pytest.raises(ValidationError, match="db_pool_min_must_not_exceed_db_pool_max"):
        _settings(db_pool_min=2, db_pool_max=1)


def test_settings_reject_control_store_inside_a_source_database() -> None:
    with pytest.raises(ValidationError, match="control_database_must_be_separate"):
        _settings(mcp_control_database_url="postgresql://writer:secret@db/orient")


def test_settings_reject_duplicate_sources() -> None:
    with pytest.raises(ValidationError, match="duplicate_or_excessive_databases"):
        _settings(orient_additional_databases="garage,garage")


def test_settings_require_tls_for_production_connections() -> None:
    with pytest.raises(ValidationError, match="production_database_tls_required"):
        _settings(environment="production")


def test_http_sources_require_no_database_credentials() -> None:
    settings = _settings(
        orient_source_transport="http",
        orient_database_url=None,
        orient_api_base_url="https://motors.itpoint.uz",
        orient_api_environment="production",
        orient_api_service_key="synthetic-key",
        orient_api_primary_database="orient_test",
    )
    assert settings.orient_database_url is None


@pytest.mark.parametrize(
    "changes",
    [
        {"orient_api_primary_database": ""},
        {"orient_api_service_key": ""},
        {"orient_api_base_url": "https://dev.avision.uz"},
        {"orient_api_base_url": "http://motors.itpoint.uz"},
        {"mcp_control_database_url": "postgresql://control:secret@db/orient_test"},
    ],
)
def test_http_source_settings_fail_closed(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "orient_source_transport": "http",
        "orient_database_url": None,
        "orient_api_base_url": "https://motors.itpoint.uz",
        "orient_api_environment": "production",
        "orient_api_service_key": "synthetic-key",
        "orient_api_primary_database": "orient_test",
        **changes,
    }
    with pytest.raises(ValidationError):
        _settings(**values)
