# tests/unit/test_cursor_service.py
# ============================================================================
# Cursor Codec Tests
#
# Verifies pagination cursors are scoped, bounded, and tamper evident.
# ============================================================================

from __future__ import annotations

import pytest

from app.domain.errors import QueryValidationError
from app.services.cursor_service import CursorCodec


def test_cursor_round_trip_returns_offset() -> None:
    codec = CursorCodec("0123456789abcdef", max_offset=100)
    cursor = codec.encode(entity="public.orders", offset=20, fingerprint="v1")

    assert codec.decode(cursor, entity="public.orders", fingerprint="v1") == 20


def test_cursor_rejects_tampering_and_cross_entity_reuse() -> None:
    codec = CursorCodec("0123456789abcdef", max_offset=100)
    cursor = codec.encode(entity="public.orders", offset=20, fingerprint="v1")

    with pytest.raises(QueryValidationError, match="invalid_cursor"):
        codec.decode(cursor + "x", entity="public.orders", fingerprint="v1")
    with pytest.raises(QueryValidationError, match="invalid_cursor"):
        codec.decode(cursor, entity="public.items", fingerprint="v1")


def test_cursor_rejects_deep_scan() -> None:
    codec = CursorCodec("0123456789abcdef", max_offset=10)
    cursor = codec.encode(entity="public.orders", offset=11, fingerprint="v1")

    with pytest.raises(QueryValidationError, match="invalid_cursor"):
        codec.decode(cursor, entity="public.orders", fingerprint="v1")
