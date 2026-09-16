# app/presentation/mcp/oauth_routes.py
# ============================================================================
# MCP OAuth HTTP Routes
#
# Exposes discovery, dynamic client registration, Authorization Code with PKCE,
# refresh, and revocation endpoints required by remote MCP clients.
# ============================================================================

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.presentation.mcp.views import OAuthViews
from app.services.auth_service import IssuedTokens, OAuthError, OAuthService, PrincipalService
from app.services.security_service import RateLimitError, SecurityService

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def create_oauth_router(
    *,
    oauth: OAuthService,
    principals: PrincipalService,
    security: SecurityService,
    views: OAuthViews,
    base_url: str,
    resource: str,
    max_request_bytes: int,
) -> APIRouter:
    router = APIRouter(tags=["mcp-oauth"])
    base = base_url.rstrip("/")

    protected_metadata = {
        "resource": resource,
        "authorization_servers": [base],
        "scopes_supported": ["orient:read", "offline_access"],
        "bearer_methods_supported": ["header"],
    }
    authorization_metadata = {
        "issuer": base,
        "authorization_endpoint": f"{base}/mcp/oauth/authorize",
        "token_endpoint": f"{base}/mcp/oauth/token",
        "registration_endpoint": f"{base}/mcp/oauth/register",
        "revocation_endpoint": f"{base}/mcp/oauth/revoke",
        "scopes_supported": ["orient:read", "offline_access"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }

    @router.get("/.well-known/oauth-protected-resource")
    @router.get("/.well-known/oauth-protected-resource/mcp")
    async def protected_resource() -> JSONResponse:
        return JSONResponse(protected_metadata)

    @router.get("/.well-known/oauth-authorization-server")
    async def authorization_server() -> JSONResponse:
        return JSONResponse(authorization_metadata)

    @router.post("/mcp/oauth/register")
    async def register(request: Request) -> JSONResponse:
        if _too_large(request, max_request_bytes):
            return JSONResponse(
                {"error": "invalid_client_metadata", "error_description": "payload_too_large"},
                status_code=413,
            )
        client_ip = _client_ip(request)
        try:
            await security.assert_allowed(client_ip, "register")
        except RateLimitError as exc:
            return JSONResponse(
                {"error": "invalid_client_metadata", "error_description": "too_many_attempts"},
                status_code=429,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )
        try:
            metadata = await request.json()
            if not isinstance(metadata, dict):
                raise ValueError
            client = await oauth.register_client(metadata)
        except ValueError:
            await security.record(client_ip, "register", False)
            return JSONResponse(
                {"error": "invalid_client_metadata", "error_description": "invalid_json"},
                status_code=400,
            )
        except OAuthError as exc:
            await security.record(client_ip, "register", False)
            return _oauth_error(exc)
        await security.record(client_ip, "register", True)
        return JSONResponse(
            {
                "client_id": client.client_id,
                "client_name": client.client_name,
                "redirect_uris": client.redirect_uris,
                "grant_types": client.grant_types,
                "response_types": client.response_types,
                "scope": client.scope,
                "token_endpoint_auth_method": "none",
                "client_id_issued_at": int(client.created_at.timestamp()),
            },
            status_code=201,
            headers=_NO_STORE,
        )

    @router.get("/mcp/oauth/authorize")
    async def authorize_get(request: Request) -> HTMLResponse:
        params = request.query_params
        language = _language(params.get("ui_locales"))
        try:
            request_id = await oauth.begin_authorization(
                client_id=params.get("client_id", ""),
                redirect_uri=params.get("redirect_uri", ""),
                scope=params.get("scope", "orient:read offline_access"),
                state=params.get("state"),
                resource=params.get("resource", resource),
                response_type=params.get("response_type", ""),
                code_challenge=params.get("code_challenge", ""),
                code_challenge_method=params.get("code_challenge_method", ""),
                client_ip_hash=security.hash_ip(_client_ip(request)),
            )
        except OAuthError as exc:
            return HTMLResponse(
                views.error_page(exc.description, language),
                status_code=exc.status_code,
            )
        return HTMLResponse(views.login_page(request_id, language), headers=_NO_STORE)

    @router.post("/mcp/oauth/authorize", response_model=None)
    async def authorize_post(
        request: Request,
        request_id: str = Form(...),
        login: str = Form(...),
        password: str = Form(...),
        language: str = Form("ru"),
    ) -> HTMLResponse | RedirectResponse:
        client_ip = _client_ip(request)
        try:
            await security.assert_allowed(client_ip, "login")
        except RateLimitError as exc:
            return HTMLResponse(
                views.error_page("too_many_attempts", language),
                status_code=429,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )
        principal = await principals.authenticate(login, password)
        await security.record(client_ip, "login", principal is not None)
        if principal is None:
            return HTMLResponse(
                views.login_page(request_id, language, "invalid_credentials"),
                status_code=401,
                headers=_NO_STORE,
            )
        try:
            raw_code, auth_request = await oauth.issue_authorization_code(request_id, principal)
        except OAuthError as exc:
            return HTMLResponse(
                views.login_page(request_id, language, exc.description),
                status_code=exc.status_code,
                headers=_NO_STORE,
            )
        query = {"code": raw_code}
        if auth_request.state:
            query["state"] = auth_request.state
        return RedirectResponse(
            f"{auth_request.redirect_uri}?{urlencode(query)}",
            status_code=302,
            headers=_NO_STORE,
        )

    @router.post("/mcp/oauth/token")
    async def token(
        grant_type: str = Form(...),
        client_id: str = Form(""),
        code: str = Form(""),
        redirect_uri: str = Form(""),
        code_verifier: str = Form(""),
        refresh_token: str = Form(""),
        resource_parameter: str = Form("", alias="resource"),
    ) -> JSONResponse:
        target_resource = resource_parameter or resource
        try:
            if grant_type == "authorization_code":
                issued = await oauth.exchange_code(
                    code=code,
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    code_verifier=code_verifier,
                    resource=target_resource,
                )
            elif grant_type == "refresh_token":
                issued = await oauth.refresh(
                    refresh_token=refresh_token,
                    client_id=client_id,
                    resource=target_resource,
                )
            else:
                return JSONResponse(
                    {
                        "error": "unsupported_grant_type",
                        "error_description": "unsupported_grant_type",
                    },
                    status_code=400,
                    headers=_NO_STORE,
                )
        except OAuthError as exc:
            return _oauth_error(exc)
        return JSONResponse(_token_body(issued), headers=_NO_STORE)

    @router.post("/mcp/oauth/revoke")
    async def revoke(token: str = Form(...)) -> JSONResponse:
        try:
            await oauth.revoke(token)
        except Exception:
            pass
        return JSONResponse({}, headers=_NO_STORE)

    return router


def _oauth_error(error: OAuthError) -> JSONResponse:
    return JSONResponse(
        {"error": error.code, "error_description": error.description},
        status_code=error.status_code,
        headers=_NO_STORE,
    )


def _token_body(tokens: IssuedTokens) -> dict[str, object]:
    body: dict[str, object] = {
        "access_token": tokens.access_token,
        "token_type": tokens.token_type,
        "expires_in": tokens.expires_in,
        "scope": tokens.scope,
    }
    if tokens.refresh_token:
        body["refresh_token"] = tokens.refresh_token
    return body


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


def _too_large(request: Request, max_bytes: int) -> bool:
    value = request.headers.get("content-length")
    try:
        return value is not None and int(value) > max_bytes
    except ValueError:
        return False


def _language(ui_locales: str | None) -> str:
    values = (ui_locales or "").split()
    candidate = values[0][:2].lower() if values else "ru"
    return candidate if candidate in {"ru", "uz", "en"} else "ru"
