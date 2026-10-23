# app/infrastructure/http/source_client.py
# ============================================================================
# Orient Source HTTP Transport
#
# Reuses connections for typed source reads and verifies the environment and
# source on every response. It has no PostgreSQL transport fallback.
# ============================================================================
from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from app.domain.data_api import DataAction, DataEnvironment, DataReadReply, DataReadRequest
from app.domain.errors import DataSourceUnavailableError


class OrientSourceHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_key: str,
        source: str,
        environment: DataEnvironment,
        timeout_seconds: float = 7,
        expected_database: str = "",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.source = source
        self.environment = environment
        self.base_url = base_url.rstrip("/")
        self.service_key = service_key
        self.timeout_seconds = timeout_seconds
        self.expected_database = expected_database
        self._owns_client = http_client is None
        self.http = http_client or httpx.AsyncClient(
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=False,
        )

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        if self._owns_client:
            await self.http.aclose()

    async def read(self, action: DataAction, **values: Any) -> DataReadReply:
        command = DataReadRequest(
            source=self.source,
            action=action,
            environment=self.environment,
            **values,
        )
        try:
            async with self.http.stream(
                "POST",
                f"{self.base_url}/users/internal/orient-mcp/v1/read",
                headers={"X-Api-Key": self.service_key},
                json=command.model_dump(mode="json", exclude_none=True),
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1_048_576:
                        raise DataSourceUnavailableError("source_response_too_large")
                reply = DataReadReply.model_validate_json(body)
        except (httpx.HTTPError, ValidationError) as exc:
            raise DataSourceUnavailableError("orient_read_api_unavailable") from exc
        if (
            reply.source != command.source
            or reply.environment != command.environment
            or reply.action != action
        ):
            raise DataSourceUnavailableError("orient_read_api_source_mismatch")
        if self.expected_database and reply.source_database != self.expected_database:
            raise DataSourceUnavailableError("orient_read_api_database_mismatch")
        return reply
