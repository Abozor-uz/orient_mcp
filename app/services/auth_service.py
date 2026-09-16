# app/services/auth_service.py
# ============================================================================
# MCP OAuth 2.1 Services
#
# Implements dynamic client registration, Authorization Code with PKCE S256,
# opaque access tokens, refresh rotation, revocation, and principal login.
# ============================================================================

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import bcrypt

from app.domain.auth import (
    AuthorizationCode,
    AuthorizationRequest,
    OAuthClient,
    OAuthScope,
    OAuthToken,
    ServicePrincipal,
    TokenFamily,
    TokenType,
)
from app.domain.auth_ports import ControlStorePort
from app.infrastructure.token_security import (
    generate_token,
    token_hash,
    verify_constant_time,
    verify_pkce_s256,
)


class OAuthError(Exception):
    def __init__(self, code: str, description: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.description = description
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    scope: str
    refresh_token: str | None = None
    token_type: str = "Bearer"


class PrincipalService:
    def __init__(self, store: ControlStorePort, login: str, password_hash: str) -> None:
        self._store = store
        self._login = login
        self._password_hash = password_hash

    async def authenticate(self, login: str, password: str) -> ServicePrincipal | None:
        if not verify_constant_time(self._login, login):
            return None
        principal = await self._store.get_active_principal(self._login)
        if principal is None or OAuthScope.ORIENT_READ not in principal.scopes:
            return None
        try:
            valid = bcrypt.checkpw(password.encode("utf-8"), self._password_hash.encode("utf-8"))
        except ValueError:
            return None
        return principal if valid else None


class OAuthService:
    SUPPORTED_SCOPES = {OAuthScope.ORIENT_READ.value, OAuthScope.OFFLINE_ACCESS.value}

    def __init__(
        self,
        store: ControlStorePort,
        *,
        public_base_url: str,
        principal_login: str,
        access_ttl_seconds: int,
        refresh_ttl_days: int,
        code_ttl_seconds: int,
        request_ttl_seconds: int,
        allowed_redirect_origins: list[str],
    ) -> None:
        self._store = store
        self.base_url = public_base_url.rstrip("/")
        self.resource = f"{self.base_url}/mcp"
        self._principal_login = principal_login
        self._access_ttl = timedelta(seconds=access_ttl_seconds)
        self._refresh_ttl = timedelta(days=refresh_ttl_days)
        self._code_ttl = timedelta(seconds=code_ttl_seconds)
        self._request_ttl = timedelta(seconds=request_ttl_seconds)
        self._allowed_redirect_origins = {
            item.rstrip("/") for item in allowed_redirect_origins if item
        }

    async def register_client(self, metadata: dict[str, Any]) -> OAuthClient:
        redirect_uris = metadata.get("redirect_uris")
        if not isinstance(redirect_uris, list) or not redirect_uris or len(redirect_uris) > 20:
            raise OAuthError("invalid_client_metadata", "invalid_client_metadata")
        normalized = [self._validate_redirect_uri(str(uri)) for uri in redirect_uris]
        grant_types = metadata.get("grant_types", ["authorization_code", "refresh_token"])
        response_types = metadata.get("response_types", ["code"])
        if (
            not isinstance(grant_types, list)
            or "authorization_code" not in grant_types
            or any(item not in {"authorization_code", "refresh_token"} for item in grant_types)
            or response_types != ["code"]
            or metadata.get("token_endpoint_auth_method", "none") != "none"
        ):
            raise OAuthError("invalid_client_metadata", "unsupported_grant")
        scope = self._normalize_scope(metadata.get("scope", "orient:read offline_access"))
        now = datetime.now(UTC)
        safe_metadata = {
            str(key)[:80]: value
            for key, value in metadata.items()
            if key != "client_secret" and len(str(value)) <= 4096
        }
        client = OAuthClient(
            id=str(uuid.uuid4()),
            client_id=generate_token(),
            client_name=str(metadata.get("client_name", "Orient MCP Client"))[:200],
            redirect_uris=normalized,
            grant_types=[str(item) for item in grant_types],
            response_types=["code"],
            scope=scope,
            token_endpoint_auth_method="none",
            metadata=safe_metadata,
            created_at=now,
            updated_at=now,
        )
        created = await self._store.create_client(client)
        if created is None:
            raise OAuthError("server_error", "server_error", 500)
        return created

    async def begin_authorization(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scope: str,
        state: str | None,
        resource: str,
        response_type: str,
        code_challenge: str,
        code_challenge_method: str,
        client_ip_hash: str | None = None,
        user_agent_hash: str | None = None,
    ) -> str:
        client = await self._require_client(client_id, redirect_uri)
        if response_type != "code" or code_challenge_method != "S256" or len(code_challenge) < 43:
            raise OAuthError("invalid_request", "invalid_authorization_request")
        if resource.rstrip("/") != self.resource:
            raise OAuthError("invalid_target", "invalid_resource")
        normalized_scope = self._normalize_scope(scope)
        if not set(normalized_scope.split()).issubset(set(client.scope.split())):
            raise OAuthError("invalid_scope", "invalid_scope")
        raw_request_id = generate_token()
        now = datetime.now(UTC)
        request = AuthorizationRequest(
            id=str(uuid.uuid4()),
            request_hash=token_hash(raw_request_id),
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=normalized_scope,
            state=state,
            resource=self.resource,
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=now + self._request_ttl,
            created_at=now,
            client_ip_hash=client_ip_hash,
            user_agent_hash=user_agent_hash,
        )
        if await self._store.create_request(request) is None:
            raise OAuthError("server_error", "server_error", 500)
        return raw_request_id

    async def issue_authorization_code(
        self,
        raw_request_id: str,
        principal: ServicePrincipal,
    ) -> tuple[str, AuthorizationRequest]:
        request = await self._store.get_request(token_hash(raw_request_id))
        now = datetime.now(UTC)
        if request is None or request.consumed_at is not None or request.expires_at <= now:
            raise OAuthError("invalid_request", "authorization_request_expired")
        await self._require_client(request.client_id, request.redirect_uri)
        if not await self._store.consume_request(request.request_hash):
            raise OAuthError("invalid_request", "authorization_request_expired")
        raw_code = generate_token()
        code = AuthorizationCode(
            id=str(uuid.uuid4()),
            code_hash=token_hash(raw_code),
            principal_id=principal.id,
            principal_login=principal.login,
            client_id=request.client_id,
            redirect_uri=request.redirect_uri,
            scope=request.scope,
            resource=request.resource,
            code_challenge=request.code_challenge,
            code_challenge_method=request.code_challenge_method,
            expires_at=now + self._code_ttl,
        )
        if await self._store.create_code(code) is None:
            raise OAuthError("server_error", "server_error", 500)
        return raw_code, request

    async def exchange_code(
        self,
        *,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
        resource: str,
    ) -> IssuedTokens:
        principal = await self._store.get_active_principal(self._principal_login)
        if principal is None:
            raise OAuthError("invalid_grant", "invalid_grant")
        await self._require_client(client_id, redirect_uri)
        consumed = await self._store.consume_code(token_hash(code), principal.id, client_id)
        if consumed is None:
            raise OAuthError("invalid_grant", "invalid_grant")
        if (
            consumed.redirect_uri != redirect_uri
            or consumed.resource != resource.rstrip("/")
            or not verify_pkce_s256(consumed.code_challenge, code_verifier)
        ):
            raise OAuthError("invalid_grant", "invalid_grant")
        return await self._issue_new_family(principal, client_id, consumed.scope, consumed.resource)

    async def refresh(self, *, refresh_token: str, client_id: str, resource: str) -> IssuedTokens:
        hashed = token_hash(refresh_token)
        existing = await self._store.get_token(hashed)
        now = datetime.now(UTC)
        if (
            existing is None
            or existing.token_type != TokenType.REFRESH
            or existing.client_id != client_id
            or existing.resource != resource.rstrip("/")
            or existing.expires_at <= now
            or existing.revoked_at is not None
        ):
            raise OAuthError("invalid_grant", "invalid_grant")
        if existing.consumed_at is not None or existing.replaced_by_token_id is not None:
            await self._store.revoke_family(
                existing.token_family_id, "refresh_token_reuse", "oauth"
            )
            raise OAuthError("invalid_grant", "invalid_grant")
        new_refresh_raw = generate_token()
        new_refresh = self._token_model(
            raw_token=new_refresh_raw,
            token_type=TokenType.REFRESH,
            principal_id=existing.principal_id,
            client_id=existing.client_id,
            family_id=existing.token_family_id,
            scope=existing.scope,
            resource=existing.resource,
            expires_at=now + self._refresh_ttl,
        )
        if not await self._store.rotate_refresh_token(hashed, new_refresh):
            await self._store.revoke_family(
                existing.token_family_id, "refresh_token_reuse", "oauth"
            )
            raise OAuthError("invalid_grant", "invalid_grant")
        access_raw = generate_token()
        access = self._token_model(
            raw_token=access_raw,
            token_type=TokenType.ACCESS,
            principal_id=existing.principal_id,
            client_id=existing.client_id,
            family_id=existing.token_family_id,
            scope=existing.scope,
            resource=existing.resource,
            expires_at=now + self._access_ttl,
        )
        if not await self._store.create_token(access):
            raise OAuthError("server_error", "server_error", 500)
        return IssuedTokens(
            access_token=access_raw,
            expires_in=int(self._access_ttl.total_seconds()),
            scope=existing.scope,
            refresh_token=new_refresh_raw,
        )

    async def revoke(self, raw_token: str) -> None:
        existing = await self._store.get_token(token_hash(raw_token))
        if existing is None:
            return
        if existing.token_type == TokenType.REFRESH:
            await self._store.revoke_family(existing.token_family_id, "client_revocation", "oauth")
        else:
            await self._store.revoke_token(token_hash(raw_token), "client_revocation", "oauth")

    async def _issue_new_family(
        self,
        principal: ServicePrincipal,
        client_id: str,
        scope: str,
        resource: str,
    ) -> IssuedTokens:
        now = datetime.now(UTC)
        family = TokenFamily(
            id=str(uuid.uuid4()),
            principal_id=principal.id,
            client_id=client_id,
            scope=scope,
            resource=resource,
            created_at=now,
            last_rotated_at=now,
        )
        if await self._store.create_family(family) is None:
            raise OAuthError("server_error", "server_error", 500)
        access_raw = generate_token()
        access = self._token_model(
            raw_token=access_raw,
            token_type=TokenType.ACCESS,
            principal_id=principal.id,
            client_id=client_id,
            family_id=family.id,
            scope=scope,
            resource=resource,
            expires_at=now + self._access_ttl,
        )
        if not await self._store.create_token(access):
            raise OAuthError("server_error", "server_error", 500)
        refresh_raw: str | None = None
        if OAuthScope.OFFLINE_ACCESS.value in scope.split():
            refresh_raw = generate_token()
            refresh = self._token_model(
                raw_token=refresh_raw,
                token_type=TokenType.REFRESH,
                principal_id=principal.id,
                client_id=client_id,
                family_id=family.id,
                scope=scope,
                resource=resource,
                expires_at=now + self._refresh_ttl,
            )
            if not await self._store.create_token(refresh):
                raise OAuthError("server_error", "server_error", 500)
        return IssuedTokens(
            access_token=access_raw,
            expires_in=int(self._access_ttl.total_seconds()),
            scope=scope,
            refresh_token=refresh_raw,
        )

    def _token_model(
        self,
        *,
        raw_token: str,
        token_type: TokenType,
        principal_id: str,
        client_id: str,
        family_id: str,
        scope: str,
        resource: str,
        expires_at: datetime,
    ) -> OAuthToken:
        return OAuthToken(
            id=str(uuid.uuid4()),
            token_hash=token_hash(raw_token),
            token_type=token_type,
            principal_id=principal_id,
            client_id=client_id,
            token_family_id=family_id,
            scope=scope,
            resource=resource,
            issued_at=datetime.now(UTC),
            expires_at=expires_at,
        )

    async def _require_client(self, client_id: str, redirect_uri: str) -> OAuthClient:
        client = await self._store.get_client(client_id)
        if client is None or not client.is_active or redirect_uri not in client.redirect_uris:
            raise OAuthError("invalid_request", "invalid_client")
        return client

    def _normalize_scope(self, scope: str) -> str:
        values = list(dict.fromkeys(str(scope).split()))
        if OAuthScope.ORIENT_READ.value not in values or not set(values).issubset(
            self.SUPPORTED_SCOPES
        ):
            raise OAuthError("invalid_scope", "invalid_scope")
        return " ".join(values)

    def _validate_redirect_uri(self, uri: str) -> str:
        if len(uri) > 2048 or "#" in uri:
            raise OAuthError("invalid_redirect_uri", "invalid_redirect_uri")
        parsed = urlparse(uri)
        is_local = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if (
            not parsed.netloc
            or (parsed.scheme != "https" and not is_local)
            or (
                self._allowed_redirect_origins
                and origin not in self._allowed_redirect_origins
                and not is_local
            )
        ):
            raise OAuthError("invalid_redirect_uri", "invalid_redirect_uri")
        return uri
