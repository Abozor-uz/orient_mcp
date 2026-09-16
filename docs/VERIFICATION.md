# Local verification — 2026-09-16

Result: **96 tests passed**, including real database and HTTP integration tests.

Environment: Python 3.12, native PostgreSQL 14.24 on Windows, bound exclusively
to `127.0.0.1:55479`. Synthetic `mcp_test_*` databases and temporary test roles
were created locally. The production source uses PostgreSQL 14.17; production
metadata/OAuth deployment acceptance is recorded below. Business-data acceptance
remains a separate owner check.

Passed:

- Ruff lint and format check for application, scripts and tests.
- Strict mypy: 46 application modules.
- Python compilation and `pip check`.
- NOINHERIT login with transaction-local `pg_read_all_data` activation.
- Rejection of INSERT, UPDATE, DELETE, TRUNCATE, persistent and temporary DDL.
- Discovery of tables, views, materialized-view columns and FK relations.
- Sensitive-field/JSON policy and incomplete composite-key handling.
- PINPP/PNFL and text `extra_data` exclusion in source tables and export views,
  including case/prefix/suffix variants. Hidden fields cannot be selected,
  filtered, sorted, aggregated, grouped or returned through record/FK lookups.
- Authenticated MCP requests reject these hidden fields while phone, plate and
  VIN lookups continue to work with sensitive columns present in the source.
- Pagination, filtered reads, aggregates and related-record queries.
- Primary/additional phone normalization, shared phone matches without duplicate
  customers, customer ID lookup and AND semantics for combined identifiers.
- Plate/VIN normalization, current owner joins, business owner separation,
  ownerless vehicles and stable ID pagination across duplicate identifiers.
- Rejection of empty lookups, partial VINs, wildcards, invalid limits and
  unauthorized fields in specialized lookups.
- Authenticated HTTP calls for phone, plate and VIN lookup tools.
- Rejection of unknown fields, SQL-like identifiers, unknown sources and
  cursors reused against another database or changed query.
- Complete OAuth registration, PKCE login, one-time code exchange, refresh,
  revocation and authenticated MCP requests over the ASGI HTTP transport.
- Request size enforcement for chunked bodies without Content-Length.
- Real CLI subprocess startup and network HTTP readiness.
- Idempotent control migration and metadata-only preflight subprocess.

## Render acceptance — 2026-09-16

- Service `orient-mcp` is live in Frankfurt, Abozor.gr, project
  `prj-d9lml6qjnfac73as0p50`, environment Production.
- Deployed functional commit: `41b90625`; GitHub CI passed, including PostgreSQL
  integration tests and Docker image build. Render also built the Docker image.
- OAuth discovery, dynamic registration, PKCE login, refresh and revocation
  passed over public HTTPS. Unauthenticated MCP access returns 401.
- All ten MCP tools are discoverable with read-only annotations.
- `orient_test`, `garage`, `notification`, `parser_data`, `scrap_data`, `qrmenu`
  report TLS and read-only transactions; session login is `garage_sync_ro`,
  effective transaction role is `pg_read_all_data`.
- The main policy-filtered catalog exposes 359 entities. Actual GarageCar
  metadata excludes `pinpp`, `prev_pnfl`, `extra_data` and retains plate/VIN fields.
- No business records were fetched. Migrations targeted only the new control DB.
- TLS diagnostics now use the active libpq connection: `pg_stat_ssl` returns
  NULL after SET ROLE for this login despite TLS being enabled.

Not performed: source-side migrations/write probes; business-record correctness
and search-latency acceptance; connection from the owner's actual ChatGPT UI.

The local source package contains no production credentials, table rows, database
dumps, virtual environment, database binaries or local test database files.
