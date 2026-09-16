# app/presentation/body_limit.py
# ============================================================================
# HTTP Request Size Boundary
#
# Bounds actual request bytes, including chunked bodies without Content-Length,
# before OAuth forms or MCP JSON are parsed.
# ============================================================================

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self._app(scope, receive, send)
            return
        messages: list[Message] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self._max_bytes:
                await JSONResponse({"error": "payload_too_large"}, status_code=413)(
                    scope, receive, send
                )
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        index = 0

        async def replay() -> Message:
            nonlocal index
            if index < len(messages):
                result = messages[index]
                index += 1
                return result
            return await receive()

        await self._app(scope, replay, send)
