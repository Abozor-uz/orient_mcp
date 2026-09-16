# app/services/maintenance_service.py
# ============================================================================
# MCP Control-State Maintenance
#
# Periodically removes expired authorization state, tokens, throttling rows,
# and audit summaries beyond retention without affecting active credentials.
# ============================================================================

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from app.domain.auth_ports import ControlStorePort
from app.logging_config import logger


class MaintenanceService:
    def __init__(self, store: ControlStorePort, audit_retention_days: int) -> None:
        self._store = store
        self._audit_retention = timedelta(days=audit_retention_days)

    async def run_once(self) -> int:
        now = datetime.now(UTC)
        return await self._store.cleanup(
            now=now,
            audit_before=now - self._audit_retention,
            attempts_before=now - timedelta(hours=24),
        )


class MaintenanceScheduler:
    def __init__(self, service: MaintenanceService, interval_hours: int) -> None:
        self._service = service
        self._interval_seconds = interval_hours * 3600
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="mcp-control-maintenance")

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._stop is not None:
            self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=10)
        except TimeoutError:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _run(self) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            if self._stop.is_set():
                return
            try:
                removed = await self._service.run_once()
                logger.info("mcp control maintenance completed", extra={"row_count": removed})
            except Exception as exc:
                logger.warning(
                    "mcp control maintenance failed",
                    extra={"error_type": type(exc).__name__},
                )
