# app/cli.py
# ============================================================================
# Operator CLI
#
# Provides secret-safe local helpers required before deployment.
# ============================================================================

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

import bcrypt
import psycopg
import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["hash-password", "serve", "migrate-control"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    if args.command == "hash-password":
        password = getpass.getpass("MCP password: ")
        confirmation = getpass.getpass("Repeat password: ")
        if not password or password != confirmation:
            raise SystemExit("Passwords do not match")
        print(bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"))
    elif args.command == "serve":
        # Uvicorn's Windows default is Proactor, which psycopg async cannot use.
        uvicorn.run(
            "app.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            loop="asyncio:SelectorEventLoop",
        )
    elif args.command == "migrate-control":
        from app.settings import Settings

        settings = Settings()
        with psycopg.connect(settings.mcp_control_database_url.get_secret_value()) as connection:
            connection.execute(Path("migrations/001_mcp_control.sql").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
