# app/infrastructure/postgres/pool.py
# ============================================================================
# PostgreSQL Connection Pool
#
# Provides bounded async transactions with server-side timeouts. Orient data
# transactions are explicitly read-only even when the database role is already
# configured with default_transaction_read_only.
# ============================================================================

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class PostgresPool:
    def __init__(
        self,
        *,
        connection_url: str,
        min_size: int,
        max_size: int,
        statement_timeout_ms: int,
        lock_timeout_ms: int,
        idle_transaction_timeout_ms: int,
        read_only: bool,
        read_role: str | None = None,
    ) -> None:
        self._read_only = read_only
        self._read_role = read_role
        if read_role and not read_only:
            raise ValueError("read_role_requires_read_only_pool")
        self._statement_timeout_ms = statement_timeout_ms
        self._lock_timeout_ms = lock_timeout_ms
        self._idle_transaction_timeout_ms = idle_transaction_timeout_ms
        self._pool = AsyncConnectionPool(
            conninfo=connection_url,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"autocommit": False, "row_factory": dict_row, "prepare_threshold": None},
            timeout=10,
        )

    async def open(self) -> None:
        await self._pool.open(wait=True, timeout=20)

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        async with self._pool.connection() as connection:
            async with connection.transaction():
                if self._read_only:
                    await connection.execute("SET TRANSACTION READ ONLY")
                    if self._read_role:
                        await connection.execute(
                            sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self._read_role))
                        )
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self._statement_timeout_ms),),
                )
                await connection.execute(
                    "SELECT set_config('lock_timeout', %s, true)",
                    (str(self._lock_timeout_ms),),
                )
                await connection.execute(
                    "SELECT set_config('idle_in_transaction_session_timeout', %s, true)",
                    (str(self._idle_transaction_timeout_ms),),
                )
                yield cast(AsyncConnection[dict[str, Any]], connection)
