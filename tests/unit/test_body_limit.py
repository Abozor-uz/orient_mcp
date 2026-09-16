# tests/unit/test_body_limit.py
# ============================================================================
# Request Limit Tests
#
# Confirms chunked payloads cannot bypass the transport byte limit.
# ============================================================================

from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.presentation.body_limit import BodyLimitMiddleware


async def test_chunked_request_is_rejected_before_handler() -> None:
    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, max_bytes=8)

    @app.post("/mcp")
    async def endpoint(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    async def chunks() -> AsyncIterator[bytes]:
        yield b"12345"
        yield b"67890"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/mcp", content=chunks())
        assert response.status_code == 413
        accepted = await client.post("/mcp", content=b"1234")
        assert accepted.json() == {"size": 4}
