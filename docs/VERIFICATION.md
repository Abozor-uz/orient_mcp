# Local verification — 2026-09-16

Result: **96 tests passed**, including real database and HTTP integration tests.

Environment: Python 3.12, native PostgreSQL 14.24 on Windows, bound exclusively
to `127.0.0.1:55479`. Synthetic `mcp_test_*` databases and temporary test roles
were created locally. The production source uses PostgreSQL 14.17; production
acceptance of this new server remains a separate step.

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

Not performed:

- Production MCP calls, production migrations or deployment.
- Docker image build: the local Docker Engine was unavailable. Dockerfile and
  Render Blueprint are supplied; CI includes image building and PostgreSQL 14
  integration tests, but no remote CI run is claimed.
- Render-to-Orient network acceptance and real AGM client login.

The local source package contains no production credentials, table rows, database
dumps, virtual environment, database binaries or local test database files.
