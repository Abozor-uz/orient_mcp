# app/services/cursor_service.py
# ============================================================================
# Opaque Pagination Cursor
#
# Signs bounded offset cursors so clients cannot forge arbitrary deep scans or
# reuse a cursor after the entity schema changes.
# ============================================================================

from __future__ import annotations

import base64
import hashlib
import hmac
import json

from app.domain.errors import QueryValidationError


class CursorCodec:
    def __init__(self, secret: str, max_offset: int = 10_000) -> None:
        self._secret = secret.encode("utf-8")
        self._max_offset = max_offset

    def encode(
        self,
        *,
        entity: str,
        offset: int,
        fingerprint: str,
        relation: str | None = None,
        binding: str | None = None,
    ) -> str:
        payload = {
            "entity": entity,
            "offset": offset,
            "fingerprint": fingerprint,
            "relation": relation,
            "binding": binding,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._secret, raw, hashlib.sha256).digest()
        return f"{_encode(raw)}.{_encode(signature)}"

    def decode(
        self,
        cursor: str | None,
        *,
        entity: str,
        fingerprint: str,
        relation: str | None = None,
        binding: str | None = None,
    ) -> int:
        if cursor is None:
            return 0
        try:
            encoded_payload, encoded_signature = cursor.split(".", 1)
            raw = _decode(encoded_payload)
            signature = _decode(encoded_signature)
            expected = hmac.new(self._secret, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(raw)
            offset = int(payload["offset"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise QueryValidationError("invalid_cursor") from exc
        if (
            payload.get("entity") != entity
            or payload.get("fingerprint") != fingerprint
            or payload.get("relation") != relation
            or payload.get("binding") != binding
            or offset < 0
            or offset > self._max_offset
        ):
            raise QueryValidationError("invalid_cursor")
        return offset


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
