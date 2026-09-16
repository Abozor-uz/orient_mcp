# tests/integration/conftest.py
# ============================================================================
# Local PostgreSQL Integration Fixtures
#
# Builds real isolated databases using an explicitly configured loopback admin.
# Remote endpoints are refused before any schema or role setup is attempted.
# ============================================================================

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import bcrypt
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.bootstrap.dependencies import ApplicationDependencies, build_dependencies
from app.settings import Settings


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    dsn = os.getenv("ORIENT_LOCAL_ADMIN_DATABASE_URL")
    if not dsn:
        pytest.skip("ORIENT_LOCAL_ADMIN_DATABASE_URL is required for real integration tests")
    parameters = conninfo_to_dict(dsn)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("integration_setup_requires_loopback_host")
    if parameters.get("dbname") != "postgres":
        raise RuntimeError("integration_setup_requires_local_postgres_admin_database")
    suffix = uuid4().hex[:10]
    main, other, control = (f"mcp_test_{kind}_{suffix}" for kind in ("main", "other", "control"))
    reader, writer = f"mcp_reader_{suffix}", f"mcp_control_{suffix}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD 'local-test-only'").format(
                sql.Identifier(reader)
            )
        )
        admin.execute(sql.SQL("GRANT pg_read_all_data TO {}").format(sql.Identifier(reader)))
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'local-test-only'").format(
                sql.Identifier(writer)
            )
        )
        for database in (main, other):
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(control), sql.Identifier(writer)
            )
        )
    seed = Path("tests/local/seed.sql").read_text(encoding="utf-8")
    for database in (main, other):
        with psycopg.connect(make_conninfo(dsn, dbname=database)) as connection:
            connection.execute(seed)
    control_url = make_conninfo(dsn, dbname=control, user=writer, password="local-test-only")
    with psycopg.connect(control_url) as connection:
        connection.execute(Path("migrations/001_mcp_control.sql").read_text(encoding="utf-8"))
    return Settings(
        _env_file=None,
        orient_database_url=make_conninfo(
            dsn, dbname=main, user=reader, password="local-test-only"
        ),
        orient_additional_databases=other,
        mcp_control_database_url=control_url,
        mcp_public_base_url="http://localhost:8000",
        mcp_agent_password_hash=bcrypt.hashpw(
            b"local-test-password", bcrypt.gensalt(rounds=4)
        ).decode(),
        mcp_auth_pepper="local-test-pepper-not-for-production",
        mcp_allowed_origins="http://localhost:8000",
        mcp_allowed_redirect_origins="https://chatgpt.com",
    )


@pytest.fixture
async def dependencies(integration_settings: Settings) -> AsyncIterator[ApplicationDependencies]:
    deps = build_dependencies(integration_settings)
    await deps.start()
    try:
        yield deps
    finally:
        await deps.stop()
