# Orient MCP operations

## Production acceptance, to run after deployment is authorized

1. Provision a separate control database and its owner login. Configure all
   secrets in Render. Reuse the existing `garage_sync_ro` source login without
   modifying its grants or Garage configuration.
2. Validate source connectivity from the actual Render service environment.
   A successful local connection does not establish Render network reachability.
   Use `python scripts/preflight.py`; it reads only catalogs/context, does not
   apply migrations and does not attempt write-rejection probes.
3. The pre-deploy command applies `001_mcp_control.sql` to the control database.
   Start the service and require `/health/ready` 200 with all configured sources.
4. Connect AGM Digital Analyst to `https://<service>/mcp`; use the configured
   analyst login/password through the OAuth page. Check client discovery,
   PKCE login, tool listing, refresh and revocation.
5. Call `list_sources`, `get_current_context`, `list_entities` and
   `get_entity_fields` for `public.carwash_carwashorder` and `public.users`.
   Require transaction_read_only=true, effective user=pg_read_all_data,
   session_user=garage_sync_ro, TLS=true, expected database and replica status.
6. Read one explicitly selected non-secret record and a small filtered aggregate
   for a known business case. Compare against an existing trusted report.
   Repeat with an additional source if enabled. Avoid full-table COUNT scans.
   For an authorized known customer, check `search_customers` with primary phone,
   additional phone and numeric ID; then `search_vehicles` with that customer ID,
   plate and VIN. Compare ownership against Orient, retain duplicate matches and
   follow `next_after_id` where present. Record latency, not identifiers/results.
   Normalized comparisons may scan rows; keep the 5-second timeout and assess
   real latency before considering separately approved source indexes.
7. Confirm password/token fields are absent, source selection rejects arbitrary
   databases, cursors progress, and a restart preserves OAuth token validity.
8. Inspect sanitized audit metadata and timeout behavior. Do not run INSERT,
   UPDATE, DELETE, CREATE or negative write probes against production.

The test suite's negative write probes run only against synthetic local databases.
No source-side migration, extension, view, function, role or firewall change is part
of deployment. Readiness intentionally fails if any configured source is missing
or inaccessible; remove an optional source from configuration if it is not needed.

## Capacity and failures

Default per-source pool: min 0 / max 2; six configured databases can use at most
12 source connections plus two control connections per service instance. Each SQL
statement has a 5-second timeout, locks 1 second, idle transaction 5 seconds.
Do not increase instance count or pool sizes without considering this total.
Control storage is required for authentication and readiness. Audit failures are
logged without recording SQL, filters, records, passwords or access tokens.

Disable a bad release by stopping/reverting the MCP service. This does not require
rolling back anything in Orient. Credential rotation for the shared Garage role
must be coordinated with Garage. Prefer a separate login later if independent
rotation and attribution become necessary.

## Sources used during implementation

- Existing Tizim MCP architecture and OAuth implementation.
- Orient infrastructure master dated 2026-04-13 and database server profile.
- Orient service catalog and the thirteen business-module documents.
- Garage PostgreSQL client and the garage_export setup migration.
- Live metadata-only access audit dated 2026-09-16.

The implementation turn performs no production queries or deployment. The prior
audit established access, while the new MCP code is verified on synthetic local
PostgreSQL before later production acceptance.
