# scripts/preflight.py
# ============================================================================
# Source Preflight
#
# Checks only source metadata and read-only context. Does not initialize OAuth,
# run migrations, issue negative write probes, or retrieve business records.
# ============================================================================

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bootstrap.sources import build_source  # noqa: E402
from app.settings import Settings  # noqa: E402


async def check() -> None:
    settings = Settings()
    sources = [build_source(settings, settings.data_source_label)]
    sources.extend(build_source(settings, name, name) for name in settings.additional_databases)
    for source in sources:
        try:
            await source.data_pool.open()
            context = await source.context_service.get_context()
            if settings.environment == "production" and not context.tls:
                raise RuntimeError("tls_required")
            print(json.dumps(context.model_dump(mode="json"), ensure_ascii=False))
        finally:
            await source.data_pool.close()


if __name__ == "__main__":
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(check())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
