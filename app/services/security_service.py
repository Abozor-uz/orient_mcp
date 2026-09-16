# app/services/security_service.py
# ============================================================================
# OAuth Abuse Protection
#
# Applies a sliding-window throttle to public login and client-registration
# routes while persisting only a salted hash of the caller IP.
# ============================================================================

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from app.domain.auth_ports import ControlStorePort
from app.logging_config import logger


class RateLimitError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("too_many_attempts")
        self.retry_after_seconds = retry_after_seconds


class SecurityService:
    def __init__(
        self,
        store: ControlStorePort,
        *,
        pepper: str,
        login_max_failures: int,
        register_max_failures: int,
        window_minutes: int,
    ) -> None:
        self._store = store
        self._pepper = pepper.encode("utf-8")
        self._login_max = login_max_failures
        self._register_max = register_max_failures
        self._window = timedelta(minutes=window_minutes)

    def hash_ip(self, value: str | None) -> str:
        return hmac.new(
            self._pepper,
            (value or "unknown").encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def assert_allowed(self, ip_address: str | None, action: str) -> None:
        limit = self._login_max if action == "login" else self._register_max
        since = datetime.now(UTC) - self._window
        try:
            failures = await self._store.count_failures_since(
                self.hash_ip(ip_address), action, since
            )
        except Exception as exc:
            logger.warning(
                "oauth throttle store unavailable",
                extra={"error_type": type(exc).__name__},
            )
            return
        if failures >= limit:
            raise RateLimitError(int(self._window.total_seconds()))

    async def record(self, ip_address: str | None, action: str, success: bool) -> None:
        try:
            await self._store.record_attempt(self.hash_ip(ip_address), action, success)
        except Exception as exc:
            logger.warning(
                "oauth throttle write unavailable",
                extra={"error_type": type(exc).__name__},
            )
