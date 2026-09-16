# app/services/audit_service.py
# ============================================================================
# Sanitized MCP Audit Service
#
# Records one outcome per tool call without persisting arguments, result rows,
# SQL, credentials, or personally identifiable information.
# ============================================================================

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from app.domain.auth import RequestIdentity
from app.domain.auth_ports import ControlStorePort
from app.logging_config import logger


class AuditService:
    def __init__(self, store: ControlStorePort) -> None:
        self._store = store

    @asynccontextmanager
    async def operation(
        self,
        identity: RequestIdentity,
        tool_name: str,
        entity: str | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        started = time.monotonic()
        success = True
        error_code: str | None = None
        metadata: dict[str, object] = {}
        if entity:
            metadata["entity"] = entity
        try:
            yield metadata
        except Exception as exc:
            success = False
            error_code = type(exc).__name__
            raise
        finally:
            response_count = metadata.pop("result_count", None)
            payload = {
                "id": str(uuid.uuid4()),
                "principal_id": identity.principal_id,
                "client_id": identity.client_id,
                "token_family_id": identity.token_family_id,
                "request_id": identity.request_id,
                "tool_name": tool_name,
                "operation": "read",
                "resource": identity.resource,
                "scope": identity.scope,
                "status": "success" if success else "failed",
                "error_code": error_code,
                "success": success,
                "duration_ms": (time.monotonic() - started) * 1000,
                "response_count": response_count,
                "metadata": metadata,
                "created_at": datetime.now(UTC),
            }
            try:
                await self._store.append_audit(payload)
            except Exception as exc:
                logger.warning(
                    "audit store unavailable",
                    extra={"tool": tool_name, "error_type": type(exc).__name__},
                )
