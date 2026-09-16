# app/presentation/mcp/token_verifier.py
# ============================================================================
# MCP Opaque Access Token Verifier
#
# Enforces token type, expiry, revocation, exact resource binding, read scope,
# and active shared-principal ownership before the MCP SDK accepts a request.
# ============================================================================

from __future__ import annotations

from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.domain.auth import OAuthScope, TokenType
from app.domain.auth_ports import ControlStorePort
from app.infrastructure.token_security import token_hash
from app.logging_config import logger


class AccessTokenVerifier(TokenVerifier):
    def __init__(self, store: ControlStorePort, *, resource: str, principal_login: str) -> None:
        self._store = store
        self._resource = resource.rstrip("/")
        self._principal_login = principal_login

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            record = await self._store.get_token(token_hash(token))
            if (
                record is None
                or record.token_type != TokenType.ACCESS
                or not record.is_active
                or record.resource != self._resource
                or OAuthScope.ORIENT_READ.value not in record.scope.split()
            ):
                return None
            principal = await self._store.get_active_principal(self._principal_login)
            if principal is None or principal.id != record.principal_id:
                return None
            return AccessToken(
                token=token,
                client_id=record.client_id,
                scopes=record.scope.split(),
                expires_at=int(record.expires_at.timestamp()),
                resource=record.resource,
                subject=principal.id,
                claims={
                    "principal_login": principal.login,
                    "token_family_id": record.token_family_id,
                },
            )
        except Exception as exc:
            logger.warning(
                "access token verification failed",
                extra={"error_type": type(exc).__name__},
            )
            return None
