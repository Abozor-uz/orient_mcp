# app/infrastructure/postgres/control_repository.py
# ============================================================================
# PostgreSQL MCP Control Repository
#
# Persists OAuth 2.1 state, refresh-token rotation, rate-limit attempts, and
# sanitized audit summaries in a database separate from the Orient datasource.
# ============================================================================

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from app.domain.auth import (
    AuthorizationCode,
    AuthorizationRequest,
    OAuthClient,
    OAuthScope,
    OAuthToken,
    PrincipalStatus,
    ServicePrincipal,
    TokenFamily,
    TokenType,
)
from app.infrastructure.postgres.pool import PostgresPool


class PostgresControlRepository:
    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def ensure_principal(self, login: str, display_name: str) -> ServicePrincipal:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO mcp_control.service_principals (login, display_name, scopes)
                VALUES (%s, %s, ARRAY['orient:read']::text[])
                ON CONFLICT (login) DO UPDATE
                SET display_name = EXCLUDED.display_name, updated_at = now()
                RETURNING *
                """,
                (login, display_name),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("principal_seed_failed")
        return _principal(row)

    async def get_active_principal(self, login: str) -> ServicePrincipal | None:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM mcp_control.service_principals
                WHERE login = %s AND status = 'active'
                LIMIT 1
                """,
                (login,),
            )
            row = await cursor.fetchone()
        return _principal(row) if row else None

    async def create_client(self, client: OAuthClient) -> OAuthClient | None:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO mcp_control.oauth_clients (
                    id, client_id, client_name, redirect_uris, grant_types,
                    response_types, scope, token_endpoint_auth_method, metadata,
                    is_active, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    client.id,
                    client.client_id,
                    client.client_name,
                    Jsonb(client.redirect_uris),
                    Jsonb(client.grant_types),
                    Jsonb(client.response_types),
                    client.scope,
                    client.token_endpoint_auth_method,
                    Jsonb(client.metadata),
                    client.is_active,
                    client.created_at,
                    client.updated_at,
                ),
            )
            row = await cursor.fetchone()
        return _client(row) if row else None

    async def get_client(self, client_id: str) -> OAuthClient | None:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM mcp_control.oauth_clients WHERE client_id = %s LIMIT 1",
                (client_id,),
            )
            row = await cursor.fetchone()
        return _client(row) if row else None

    async def create_request(self, request: AuthorizationRequest) -> AuthorizationRequest | None:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO mcp_control.authorization_requests (
                    id, request_hash, client_id, redirect_uri, scope, state,
                    resource, code_challenge, code_challenge_method, principal_id,
                    principal_login, expires_at, created_at, consumed_at,
                    client_ip_hash, user_agent_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING *
                """,
                (
                    request.id,
                    request.request_hash,
                    request.client_id,
                    request.redirect_uri,
                    request.scope,
                    request.state,
                    request.resource,
                    request.code_challenge,
                    request.code_challenge_method,
                    request.principal_id,
                    request.principal_login,
                    request.expires_at,
                    request.created_at,
                    request.consumed_at,
                    request.client_ip_hash,
                    request.user_agent_hash,
                ),
            )
            row = await cursor.fetchone()
        return _request(row) if row else None

    async def get_request(self, request_hash: str) -> AuthorizationRequest | None:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM mcp_control.authorization_requests
                WHERE request_hash = %s LIMIT 1
                """,
                (request_hash,),
            )
            row = await cursor.fetchone()
        return _request(row) if row else None

    async def consume_request(self, request_hash: str) -> bool:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE mcp_control.authorization_requests
                SET consumed_at = now()
                WHERE request_hash = %s
                  AND consumed_at IS NULL
                  AND expires_at > now()
                RETURNING id
                """,
                (request_hash,),
            )
            row = await cursor.fetchone()
        return row is not None

    async def create_code(self, code: AuthorizationCode) -> AuthorizationCode | None:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO mcp_control.authorization_codes (
                    id, code_hash, principal_id, principal_login, client_id,
                    redirect_uri, scope, resource, code_challenge,
                    code_challenge_method, expires_at, consumed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    code.id,
                    code.code_hash,
                    code.principal_id,
                    code.principal_login,
                    code.client_id,
                    code.redirect_uri,
                    code.scope,
                    code.resource,
                    code.code_challenge,
                    code.code_challenge_method,
                    code.expires_at,
                    code.consumed_at,
                ),
            )
            row = await cursor.fetchone()
        return _code(row) if row else None

    async def consume_code(
        self,
        code_hash: str,
        principal_id: str,
        client_id: str,
    ) -> AuthorizationCode | None:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE mcp_control.authorization_codes
                SET consumed_at = now()
                WHERE code_hash = %s
                  AND principal_id = %s
                  AND client_id = %s
                  AND consumed_at IS NULL
                  AND expires_at > now()
                RETURNING *
                """,
                (code_hash, principal_id, client_id),
            )
            row = await cursor.fetchone()
        return _code(row) if row else None

    async def create_family(self, family: TokenFamily) -> TokenFamily | None:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO mcp_control.token_families (
                    id, principal_id, client_id, scope, resource, revoked_at,
                    revoke_reason, created_at, last_rotated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    family.id,
                    family.principal_id,
                    family.client_id,
                    family.scope,
                    family.resource,
                    family.revoked_at,
                    family.revoke_reason,
                    family.created_at,
                    family.last_rotated_at,
                ),
            )
            row = await cursor.fetchone()
        return _family(row) if row else None

    async def create_token(self, token: OAuthToken) -> bool:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO mcp_control.oauth_tokens (
                    id, token_hash, token_type, principal_id, client_id,
                    token_family_id, scope, resource, issued_at, expires_at,
                    consumed_at, revoked_at, revoke_reason, revoked_by,
                    replaced_by_token_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                _token_values(token),
            )
        return cursor.rowcount == 1

    async def get_token(self, hashed_token: str) -> OAuthToken | None:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM mcp_control.oauth_tokens WHERE token_hash = %s LIMIT 1",
                (hashed_token,),
            )
            row = await cursor.fetchone()
        return _token(row) if row else None

    async def rotate_refresh_token(self, hashed_token: str, new_token: OAuthToken) -> bool:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM mcp_control.oauth_tokens
                WHERE token_hash = %s FOR UPDATE
                """,
                (hashed_token,),
            )
            existing = await cursor.fetchone()
            if (
                existing is None
                or existing["token_type"] != "refresh"
                or existing["consumed_at"] is not None
                or existing["revoked_at"] is not None
                or existing["expires_at"] <= new_token.issued_at
                or str(existing["token_family_id"]) != new_token.token_family_id
            ):
                return False
            await connection.execute(
                """
                INSERT INTO mcp_control.oauth_tokens (
                    id, token_hash, token_type, principal_id, client_id,
                    token_family_id, scope, resource, issued_at, expires_at,
                    consumed_at, revoked_at, revoke_reason, revoked_by,
                    replaced_by_token_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                _token_values(new_token),
            )
            await connection.execute(
                """
                UPDATE mcp_control.oauth_tokens
                SET consumed_at = now(), replaced_by_token_id = %s
                WHERE token_hash = %s
                """,
                (new_token.id, hashed_token),
            )
            await connection.execute(
                """
                UPDATE mcp_control.token_families
                SET last_rotated_at = now()
                WHERE id = %s
                """,
                (new_token.token_family_id,),
            )
        return True

    async def revoke_token(self, hashed_token: str, reason: str, revoked_by: str) -> bool:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE mcp_control.oauth_tokens
                SET revoked_at = COALESCE(revoked_at, now()),
                    revoke_reason = %s,
                    revoked_by = %s
                WHERE token_hash = %s
                """,
                (reason, revoked_by, hashed_token),
            )
        return cursor.rowcount > 0

    async def revoke_family(self, family_id: str, reason: str, revoked_by: str) -> bool:
        async with self._pool.transaction() as connection:
            family_cursor = await connection.execute(
                """
                UPDATE mcp_control.token_families
                SET revoked_at = COALESCE(revoked_at, now()), revoke_reason = %s
                WHERE id = %s
                """,
                (reason, family_id),
            )
            await connection.execute(
                """
                UPDATE mcp_control.oauth_tokens
                SET revoked_at = COALESCE(revoked_at, now()),
                    revoke_reason = %s,
                    revoked_by = %s
                WHERE token_family_id = %s
                """,
                (reason, revoked_by, family_id),
            )
        return family_cursor.rowcount > 0

    async def record_attempt(self, ip_hash: str, action: str, success: bool) -> bool:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO mcp_control.auth_attempts (ip_hash, action, success)
                VALUES (%s, %s, %s)
                """,
                (ip_hash, action, success),
            )
        return cursor.rowcount == 1

    async def count_failures_since(self, ip_hash: str, action: str, since: datetime) -> int:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT count(*) AS count
                FROM mcp_control.auth_attempts
                WHERE ip_hash = %s
                  AND action = %s
                  AND success = false
                  AND created_at >= %s
                """,
                (ip_hash, action, since),
            )
            row = await cursor.fetchone()
        return int(row["count"]) if row else 0

    async def append_audit(self, payload: dict[str, Any]) -> bool:
        async with self._pool.transaction() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO mcp_control.audit_log (
                    id, principal_id, client_id, token_family_id, request_id,
                    tool_name, operation, resource, scope, status, error_code,
                    success, duration_ms, response_count, metadata, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    payload["id"],
                    payload["principal_id"],
                    payload.get("client_id"),
                    payload.get("token_family_id"),
                    payload.get("request_id"),
                    payload.get("tool_name"),
                    payload.get("operation", "read"),
                    payload.get("resource"),
                    payload.get("scope"),
                    payload["status"],
                    payload.get("error_code"),
                    payload["success"],
                    payload.get("duration_ms"),
                    payload.get("response_count"),
                    Jsonb(payload.get("metadata", {})),
                    payload["created_at"],
                ),
            )
        return cursor.rowcount == 1

    async def cleanup(
        self,
        *,
        now: datetime,
        audit_before: datetime,
        attempts_before: datetime,
    ) -> int:
        statements = [
            ("DELETE FROM mcp_control.authorization_requests WHERE expires_at < %s", now),
            ("DELETE FROM mcp_control.authorization_codes WHERE expires_at < %s", now),
            ("DELETE FROM mcp_control.oauth_tokens WHERE expires_at < %s", now),
            ("DELETE FROM mcp_control.auth_attempts WHERE created_at < %s", attempts_before),
            ("DELETE FROM mcp_control.audit_log WHERE created_at < %s", audit_before),
        ]
        removed = 0
        async with self._pool.transaction() as connection:
            for statement, value in statements:
                cursor = await connection.execute(statement, (value,))
                removed += max(0, cursor.rowcount)
        return removed


def _principal(row: dict[str, Any]) -> ServicePrincipal:
    return ServicePrincipal(
        id=str(row["id"]),
        login=row["login"],
        display_name=row["display_name"],
        status=PrincipalStatus(row["status"]),
        scopes=[OAuthScope(value) for value in row["scopes"]],
        locale=row["locale"],
        timezone=row["timezone"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _client(row: dict[str, Any]) -> OAuthClient:
    return OAuthClient(
        id=str(row["id"]),
        client_id=row["client_id"],
        client_name=row["client_name"],
        redirect_uris=list(row["redirect_uris"]),
        grant_types=list(row["grant_types"]),
        response_types=list(row["response_types"]),
        scope=row["scope"],
        token_endpoint_auth_method=row["token_endpoint_auth_method"],
        metadata=dict(row["metadata"]),
        is_active=row["is_active"],
        last_used_at=row["last_used_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _request(row: dict[str, Any]) -> AuthorizationRequest:
    return AuthorizationRequest(
        id=str(row["id"]),
        request_hash=row["request_hash"],
        client_id=row["client_id"],
        redirect_uri=row["redirect_uri"],
        scope=row["scope"],
        state=row["state"],
        resource=row["resource"],
        code_challenge=row["code_challenge"],
        code_challenge_method=row["code_challenge_method"],
        principal_id=str(row["principal_id"]) if row["principal_id"] else None,
        principal_login=row["principal_login"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        consumed_at=row["consumed_at"],
        client_ip_hash=row["client_ip_hash"],
        user_agent_hash=row["user_agent_hash"],
    )


def _code(row: dict[str, Any]) -> AuthorizationCode:
    return AuthorizationCode(
        id=str(row["id"]),
        code_hash=row["code_hash"],
        principal_id=str(row["principal_id"]),
        principal_login=row["principal_login"],
        client_id=row["client_id"],
        redirect_uri=row["redirect_uri"],
        scope=row["scope"],
        resource=row["resource"],
        code_challenge=row["code_challenge"],
        code_challenge_method=row["code_challenge_method"],
        expires_at=row["expires_at"],
        consumed_at=row["consumed_at"],
    )


def _family(row: dict[str, Any]) -> TokenFamily:
    return TokenFamily(
        id=str(row["id"]),
        principal_id=str(row["principal_id"]),
        client_id=row["client_id"],
        scope=row["scope"],
        resource=row["resource"],
        revoked_at=row["revoked_at"],
        revoke_reason=row["revoke_reason"],
        created_at=row["created_at"],
        last_rotated_at=row["last_rotated_at"],
    )


def _token(row: dict[str, Any]) -> OAuthToken:
    return OAuthToken(
        id=str(row["id"]),
        token_hash=row["token_hash"],
        token_type=TokenType(row["token_type"]),
        principal_id=str(row["principal_id"]),
        client_id=row["client_id"],
        token_family_id=str(row["token_family_id"]),
        scope=row["scope"],
        resource=row["resource"],
        issued_at=row["issued_at"],
        expires_at=row["expires_at"],
        consumed_at=row["consumed_at"],
        revoked_at=row["revoked_at"],
        revoke_reason=row["revoke_reason"],
        revoked_by=row["revoked_by"],
        replaced_by_token_id=str(row["replaced_by_token_id"])
        if row["replaced_by_token_id"]
        else None,
    )


def _token_values(token: OAuthToken) -> tuple[Any, ...]:
    return (
        token.id,
        token.token_hash,
        token.token_type.value,
        token.principal_id,
        token.client_id,
        token.token_family_id,
        token.scope,
        token.resource,
        token.issued_at,
        token.expires_at,
        token.consumed_at,
        token.revoked_at,
        token.revoke_reason,
        token.revoked_by,
        token.replaced_by_token_id,
    )
