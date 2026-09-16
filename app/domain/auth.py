# app/domain/auth.py
# ============================================================================
# MCP OAuth Domain Models
#
# Framework-independent models for the shared Orient Production Analyst service
# principal, OAuth clients, PKCE state, opaque tokens, and audit identity.
# ============================================================================

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PrincipalStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class OAuthScope(str, Enum):
    ORIENT_READ = "orient:read"
    OFFLINE_ACCESS = "offline_access"


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


class ServicePrincipal(BaseModel):
    id: str
    login: str
    display_name: str
    status: PrincipalStatus
    scopes: list[OAuthScope]
    locale: str = "ru"
    timezone: str = "Asia/Tashkent"
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status == PrincipalStatus.ACTIVE


class OAuthClient(BaseModel):
    id: str
    client_id: str
    client_name: str | None = None
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    scope: str
    token_endpoint_auth_method: str = "none"
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AuthorizationRequest(BaseModel):
    id: str
    request_hash: str
    client_id: str
    redirect_uri: str
    scope: str
    state: str | None = None
    resource: str
    code_challenge: str
    code_challenge_method: str = "S256"
    principal_id: str | None = None
    principal_login: str | None = None
    expires_at: datetime
    created_at: datetime
    consumed_at: datetime | None = None
    client_ip_hash: str | None = None
    user_agent_hash: str | None = None


class AuthorizationCode(BaseModel):
    id: str
    code_hash: str
    principal_id: str
    principal_login: str | None = None
    client_id: str
    redirect_uri: str
    scope: str
    resource: str
    code_challenge: str
    code_challenge_method: str = "S256"
    expires_at: datetime
    consumed_at: datetime | None = None


class TokenFamily(BaseModel):
    id: str
    principal_id: str
    client_id: str
    scope: str
    resource: str
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    created_at: datetime
    last_rotated_at: datetime


class OAuthToken(BaseModel):
    id: str
    token_hash: str
    token_type: TokenType
    principal_id: str
    client_id: str
    token_family_id: str
    scope: str
    resource: str
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    revoked_by: str | None = None
    replaced_by_token_id: str | None = None

    @property
    def is_active(self) -> bool:
        return (
            self.revoked_at is None
            and self.consumed_at is None
            and self.expires_at > datetime.now(UTC)
        )


class RequestIdentity(BaseModel):
    principal_id: str
    principal_login: str
    client_id: str
    token_family_id: str | None = None
    scope: str
    resource: str
    request_id: str | None = None
