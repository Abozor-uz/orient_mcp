# Orient MCP

Read-only MCP server for AGM Digital Analyst, built from the existing Tizim MCP
foundation and adapted to the actual Orient Motors PostgreSQL access model.

## Capabilities

- OAuth Authorization Code + PKCE, rotating refresh tokens and revocation.
- Ten tools: `list_sources`, `get_current_context`, `list_entities`,
  `get_entity_fields`, `search_records`, `get_record`, `aggregate_records`,
  `get_related_records`, `search_customers`, `search_vehicles`.
- Separate catalog, source-specific signed cursors and bounded connection pool
  per configured database. Every tool accepts `source` except `list_sources`.
- Live tables, views, materialized views, keys, indexes and foreign-key relations.
- Explicit fields, parameterized filters, SQL aggregates, query timeouts,
  100-row pages and a 1 MiB serialized tool-result ceiling.
- RU/UZ/EN business aliases and documented Orient semantics.

## Customer and vehicle search

Dedicated lookups use the original Orient tables in the main `orient` source:

```json
{"name":"search_customers","arguments":{"source":"orient","phone":"+998 (90) 123-45-67"}}
{"name":"search_customers","arguments":{"source":"orient","customer_id":123}}
{"name":"search_vehicles","arguments":{"source":"orient","customer_id":123}}
{"name":"search_vehicles","arguments":{"source":"orient","plate_number":"01 A 123 BC"}}
{"name":"search_vehicles","arguments":{"source":"orient","vin":"1HGCM82633A004352"}}
```

Examples use synthetic identifiers. Phone lookup checks `users.username` and
`user_additional_phone.number`, deduplicates customers and reports which source
matched. Nine digits mean an Uzbekistan number (+998); international prefixes
`+` and `00`, spaces, parentheses, dots and hyphens are accepted.

Vehicle lookup reads `business_account_garagecar`, maps `win_number` to `vin`,
and returns the linked user's ID, primary phone and name. `business_owner_id`
is a separate BusinessUser reference; it is never treated as a customer ID.
Vehicles without a personal owner remain visible. Ownership is the current
application relation, not evidence of legal ownership.

Plates use Latin letters/digits; spaces, hyphens and letter case are ignored.
VIN lookup accepts a complete 17-character VIN, with the same formatting rules.
Cyrillic lookalikes, wildcard and substring searches are rejected. These tools
search current garage vehicles, not previous plates or marketplace listings.
Use catalog-guided `search_records` for legacy nonstandard identifiers or other
entities. A missing field/table fails explicitly instead of silently skipping it.

At least one identifier is required. Multiple filters combine with AND. Matches
are not assumed unique. Pages contain at most 100 items; reuse the same filters
and source with `after_id` set to the returned `next_after_id`. Customers and
vehicles have separate pages, so customers with many cars cannot cause an
unbounded nested response. Queries retain source read-only transactions, catalog
field policy and timeouts. Audit records contain tool/source/count, not phone,
plate, VIN or returned records. Formatting-insensitive comparisons can scan rows
because existing indexes cover raw values; production latency must be measured
before any separately approved indexing work.

## Existing source connection

The 2026-09-16 read-only access audit confirmed `185.100.54.14:5432`, PostgreSQL
14.17, primary database `orient_test`, and the Garage login `garage_sync_ro`.
The login has `NOINHERIT` and membership in `pg_read_all_data`. Every source
transaction runs `SET TRANSACTION READ ONLY` followed by
`SET LOCAL ROLE pg_read_all_data`; switching roles is transaction-local.

The audit found 374 public tables, three views, one materialized view and eight
Garage export views. These are audit observations, not hardcoded runtime counts.
The exposed catalog is smaller because policy removes sensitive objects/fields.

Optional additional databases are `garage`, `notification`, `parser_data`,
`scrap_data` and `qrmenu`. They reuse the same host/login/TLS settings but have
separate connections. `servicelink` was empty and is not enabled by default.
Dev databases are not included. Cross-database joins and raw SQL are not exposed.

The underlying shared role can still create objects through PostgreSQL PUBLIC
privileges outside this application. This application enforces read-only
transactions and exposes no write or arbitrary-function tools; it does not change
the database role, firewall, schemas or existing Garage integration.

## Setup

Use Python 3.12. Create an isolated virtual environment and install
`requirements-dev.txt`. Copy `.env.example` to `.env` and replace placeholders.
Do not put real credentials into tracked files. URL-encode special characters
in URI passwords. Production DSNs require TLS (`require`, preferably `verify-full`
with the appropriate hostname and CA certificate).

Provide a **separate writable control database** owned by this MCP service.
Do not point it at Orient, Garage production, or an existing MCP control database.
Only this database receives OAuth/audit state; source data is never copied there.
The control schema is `mcp_control`. Its owner must be able to apply the bundled
migration. No admin PostgreSQL account is required by the running MCP.

```shell
python -m app.cli hash-password
python -m app.cli migrate-control
python -m app.cli serve --host 127.0.0.1 --port 8000
```

Set the resulting password hash as `MCP_AGENT_PASSWORD_HASH` and generate a long
random `MCP_AUTH_PEPPER`. Use the same pepper across restarts. Set
`MCP_PUBLIC_BASE_URL` to the final HTTPS service URL before connecting a client.
The MCP endpoint is `/mcp`, readiness `/health/ready`, liveness `/health/live`.

## Local verification

All integration tests use synthetic records in real PostgreSQL. Setup refuses
non-loopback admin addresses and creates uniquely named `mcp_test_*` databases.
Never run the test suite against production or through a production SSH tunnel.

```shell
docker compose -f compose.test.yaml up -d --wait
# Set ORIENT_LOCAL_ADMIN_DATABASE_URL to:
# postgresql://postgres:local-test-only@127.0.0.1:55479/postgres
ruff check app tests scripts
ruff format --check app tests scripts
mypy app
pytest -q
docker build -t orient-mcp:local .
```

PowerShell: `$env:ORIENT_LOCAL_ADMIN_DATABASE_URL='postgresql://postgres:local-test-only@127.0.0.1:55479/postgres'`.
Without that variable, integration tests are explicitly skipped. CI supplies a
PostgreSQL 14 service and runs both test levels. Local PostgreSQL 14 binaries are
also supported; the development machine used loopback port 55479.

## Deployment

`render.yaml` defines an independent paid Docker web service, disabled automatic
deploys, readiness checks and a pre-deploy migration **only for the control DB**.
Provide `ORIENT_DATABASE_URL`, `MCP_CONTROL_DATABASE_URL`, public URL and OAuth
secrets through Render. No service has been created or deployed by this package.
See [operations](docs/OPERATIONS.md) for the production acceptance sequence.

## Policy and limitations

`config/catalog_overrides.yaml` exposes business entities in `public` and
`garage_export`. Authentication/session/token tables, SQL statistics, chat bodies,
credential/document/card fields and unstructured payload fields are excluded.
JSON/JSONB and bytea columns are excluded regardless of field name. Field-name
rules also exclude PINPP/PNFL/PINFL variants (including `prev_pnfl`)
and `extra_data` payloads even when stored as text, across tables and views.
Approved business identifiers, including customer usernames/phones and vehicle references,
can be returned; this is an authenticated internal analyst, not a public API.
Schema changes are discovered at catalog refresh and evaluated by these policies.
Policy configuration is loaded at startup; restart the service after policy edits.

Query results are live reads, not consistent multi-request snapshots. Offset
pagination has a 10,000-row bound and can shift during concurrent writes. Views
without a unique key have weaker ordering guarantees. Query timestamps do not
prove freshness of underlying business events. Query timeouts may reject expensive
aggregates; refine filters instead of exporting entire tables.

## Layout

`app/domain` contains typed contracts; `app/infrastructure` contains PostgreSQL and
policy adapters; `app/services` contains read/auth orchestration;
`app/presentation` contains MCP and OAuth handlers; `app/bootstrap` composes them.
`migrations` targets only control state. `scripts/preflight.py` checks source
metadata without records or writes; `scripts/smoke_http.py` checks a deployed MCP
using an existing access token supplied in `MCP_SMOKE_ACCESS_TOKEN`.
