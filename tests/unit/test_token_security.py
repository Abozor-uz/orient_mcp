# tests/unit/test_token_security.py
# ============================================================================
# Token Security Tests
#
# Verifies opaque hashing and PKCE S256 validation behavior.
# ============================================================================

from __future__ import annotations

import base64
import hashlib

from app.infrastructure.token_security import token_hash, verify_pkce_s256


def test_token_hash_is_deterministic_without_exposing_token() -> None:
    assert token_hash("secret") == hashlib.sha256(b"secret").hexdigest()
    assert token_hash("secret") != "secret"


def test_pkce_s256_accepts_matching_verifier_only() -> None:
    verifier = "a" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )

    assert verify_pkce_s256(challenge, verifier)
    assert not verify_pkce_s256(challenge, "b" * 64)
