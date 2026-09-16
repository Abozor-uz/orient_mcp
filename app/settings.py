# app/settings.py
# ============================================================================
# Application Settings
#
# Loads and validates environment-backed configuration without exposing secret
# values in logs or model representations.
# ============================================================================

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from psycopg.conninfo import conninfo_to_dict
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    data_source_label: str = "orient"

    orient_database_url: SecretStr
    orient_additional_databases: str = ""
    orient_read_role: str = "pg_read_all_data"
    mcp_control_database_url: SecretStr
    mcp_public_base_url: str = "http://localhost:8000"
    mcp_agent_login: str = "orient_workspace_agent"
    mcp_agent_password_hash: SecretStr
    mcp_auth_pepper: SecretStr

    mcp_allowed_origins: str = "https://chatgpt.com,https://chat.openai.com"
    mcp_allowed_redirect_origins: str = "https://chatgpt.com,https://chat.openai.com"
    orient_allowed_schemas: str = "public,garage_export"
    orient_policy_path: Path = Path("config/catalog_overrides.yaml")

    db_pool_min: int = Field(default=0, ge=0, le=2)
    db_pool_max: int = Field(default=2, ge=1, le=5)
    db_statement_timeout_ms: int = Field(default=5000, ge=250, le=60000)
    db_lock_timeout_ms: int = Field(default=1000, ge=100, le=10000)
    db_idle_transaction_timeout_ms: int = Field(default=5000, ge=500, le=60000)
    catalog_ttl_seconds: int = Field(default=600, ge=30, le=86400)

    mcp_max_request_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    mcp_access_token_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    mcp_refresh_token_ttl_days: int = Field(default=180, ge=1, le=365)
    mcp_authorization_code_ttl_seconds: int = Field(default=300, ge=60, le=900)
    mcp_authorization_request_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    mcp_auth_max_failures_per_window: int = Field(default=10, ge=1, le=100)
    mcp_register_max_failures_per_window: int = Field(default=20, ge=1, le=200)
    mcp_auth_window_minutes: int = Field(default=15, ge=1, le=1440)
    mcp_audit_retention_days: int = Field(default=90, ge=1, le=3650)
    mcp_cleanup_interval_hours: int = Field(default=6, ge=1, le=168)

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> Settings:
        if self.db_pool_min > self.db_pool_max:
            raise ValueError("db_pool_min_must_not_exceed_db_pool_max")
        parsed = urlparse(self.mcp_public_base_url)
        is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not parsed.netloc or (parsed.scheme != "https" and not is_local):
            raise ValueError("mcp_public_base_url_must_use_https")
        if not self.mcp_agent_password_hash.get_secret_value():
            raise ValueError("mcp_agent_password_hash_required")
        if len(self.mcp_auth_pepper.get_secret_value()) < 16:
            raise ValueError("mcp_auth_pepper_too_short")
        data = conninfo_to_dict(self.orient_database_url.get_secret_value())
        control = conninfo_to_dict(self.mcp_control_database_url.get_secret_value())
        databases = [str(data.get("dbname", "")), *self.additional_databases]
        if len(databases) != len(set(databases)) or len(databases) > 8:
            raise ValueError("duplicate_or_excessive_databases")
        if self.data_source_label in self.additional_databases:
            raise ValueError("source_label_conflicts_with_database")
        if not all(name and len(name) <= 63 for name in databases):
            raise ValueError("invalid_database_name")
        if (data.get("host"), data.get("port", "5432")) == (
            control.get("host"),
            control.get("port", "5432"),
        ) and control.get("dbname") in databases:
            raise ValueError("control_database_must_be_separate")
        if self.environment == "production":
            for conn in (data, control):
                if conn.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
                    raise ValueError("production_database_tls_required")
        return self

    @property
    def public_base_url(self) -> str:
        return self.mcp_public_base_url.rstrip("/")

    @property
    def resource(self) -> str:
        return f"{self.public_base_url}/mcp"

    @property
    def allowed_origins(self) -> list[str]:
        return _csv(self.mcp_allowed_origins)

    @property
    def allowed_redirect_origins(self) -> list[str]:
        return _csv(self.mcp_allowed_redirect_origins)

    @property
    def allowed_schemas(self) -> list[str]:
        return _csv(self.orient_allowed_schemas)

    @property
    def additional_databases(self) -> list[str]:
        return _csv(self.orient_additional_databases)


def _csv(value: str) -> list[str]:
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


def get_settings() -> Settings:
    return Settings()
