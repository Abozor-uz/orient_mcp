# app/__init__.py
# ============================================================================
# Orient MCP Application Package
#
# Contains the read-only MCP server and its domain, infrastructure, service,
# and presentation layers. Psycopg async connections use a selector loop on
# Windows; Linux and Render retain their native event-loop policy.
# ============================================================================

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
