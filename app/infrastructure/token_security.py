# app/infrastructure/token_security.py
# ============================================================================
# OAuth Secret Helpers
#
# Generates high-entropy opaque values, stores only hashes, and verifies PKCE
# challenges using constant-time comparisons.
# ============================================================================

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


def generate_token(entropy_bytes: int = 32) -> str:
    value = secrets.token_bytes(max(32, entropy_bytes))
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_constant_time(expected: str, actual: str) -> bool:
    return hmac.compare_digest(expected, actual)


def verify_pkce_s256(challenge: str, verifier: str) -> bool:
    if not challenge or not verifier:
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verify_constant_time(expected, challenge)
