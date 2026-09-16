-- migrations/001_mcp_control.sql
-- MCP OAuth, throttling, and sanitized audit state. Apply only to the writable
-- control database, never through the Orient read-only datasource role.

begin;

create schema if not exists mcp_control;
revoke all on schema mcp_control from public;

create table if not exists mcp_control.service_principals (
    id uuid primary key default gen_random_uuid(),
    login text not null unique,
    display_name text not null,
    status text not null default 'active' check (status in ('active', 'inactive')),
    scopes text[] not null default array['orient:read']::text[],
    locale text not null default 'ru',
    timezone text not null default 'Asia/Tashkent',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists mcp_control.oauth_clients (
    id uuid primary key default gen_random_uuid(),
    client_id text not null unique,
    client_name text,
    redirect_uris jsonb not null,
    grant_types jsonb not null,
    response_types jsonb not null,
    scope text not null,
    token_endpoint_auth_method text not null default 'none',
    metadata jsonb not null default '{}'::jsonb,
    is_active boolean not null default true,
    last_used_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists mcp_control.authorization_requests (
    id uuid primary key,
    request_hash text not null unique,
    client_id text not null references mcp_control.oauth_clients(client_id),
    redirect_uri text not null,
    scope text not null,
    state text,
    resource text not null,
    code_challenge text not null,
    code_challenge_method text not null default 'S256',
    principal_id uuid references mcp_control.service_principals(id),
    principal_login text,
    expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    consumed_at timestamptz,
    client_ip_hash text,
    user_agent_hash text
);

create table if not exists mcp_control.authorization_codes (
    id uuid primary key,
    code_hash text not null unique,
    principal_id uuid not null references mcp_control.service_principals(id),
    principal_login text,
    client_id text not null references mcp_control.oauth_clients(client_id),
    redirect_uri text not null,
    scope text not null,
    resource text not null,
    code_challenge text not null,
    code_challenge_method text not null default 'S256',
    expires_at timestamptz not null,
    consumed_at timestamptz
);

create table if not exists mcp_control.token_families (
    id uuid primary key default gen_random_uuid(),
    principal_id uuid not null references mcp_control.service_principals(id),
    client_id text not null references mcp_control.oauth_clients(client_id),
    scope text not null,
    resource text not null,
    revoked_at timestamptz,
    revoke_reason text,
    created_at timestamptz not null default now(),
    last_rotated_at timestamptz not null default now()
);

create table if not exists mcp_control.oauth_tokens (
    id uuid primary key,
    token_hash text not null unique,
    token_type text not null check (token_type in ('access', 'refresh')),
    principal_id uuid not null references mcp_control.service_principals(id),
    client_id text not null references mcp_control.oauth_clients(client_id),
    token_family_id uuid not null references mcp_control.token_families(id),
    scope text not null,
    resource text not null,
    issued_at timestamptz not null,
    expires_at timestamptz not null,
    consumed_at timestamptz,
    revoked_at timestamptz,
    revoke_reason text,
    revoked_by text,
    replaced_by_token_id uuid references mcp_control.oauth_tokens(id)
);

create table if not exists mcp_control.auth_attempts (
    id bigserial primary key,
    ip_hash text not null,
    action text not null,
    success boolean not null,
    created_at timestamptz not null default now()
);

create table if not exists mcp_control.audit_log (
    id uuid primary key,
    principal_id uuid not null references mcp_control.service_principals(id),
    client_id text,
    token_family_id uuid,
    request_id text,
    tool_name text,
    operation text not null default 'read',
    resource text,
    scope text,
    status text not null,
    error_code text,
    success boolean not null,
    duration_ms double precision,
    response_count integer,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists oauth_tokens_active_idx
    on mcp_control.oauth_tokens (token_hash, expires_at) where revoked_at is null;
create index if not exists oauth_tokens_family_idx
    on mcp_control.oauth_tokens (token_family_id, issued_at desc);
create index if not exists authorization_requests_expiry_idx
    on mcp_control.authorization_requests (expires_at);
create index if not exists authorization_codes_expiry_idx
    on mcp_control.authorization_codes (expires_at);
create index if not exists auth_attempts_window_idx
    on mcp_control.auth_attempts (ip_hash, action, created_at desc);
create index if not exists audit_log_created_idx
    on mcp_control.audit_log (created_at desc);

commit;
