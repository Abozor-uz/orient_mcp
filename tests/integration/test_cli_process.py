# tests/integration/test_cli_process.py
# ============================================================================
# Process Startup Acceptance
#
# Runs the operator CLI, migration and metadata preflight as real subprocesses
# against the isolated local fixtures, then checks the listening HTTP server.
# ============================================================================

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from pydantic import SecretStr

from app.settings import Settings


def test_cli_migration_preflight_and_server_start(integration_settings: Settings) -> None:
    env = dict(os.environ)
    for name in type(integration_settings).model_fields:
        value = getattr(integration_settings, name)
        env[name.upper()] = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
    for command in (["-m", "app.cli", "migrate-control"], ["scripts/preflight.py"]):
        result = subprocess.run(
            [sys.executable, *command], env=env, capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr
        if command[0].endswith("preflight.py"):
            contexts = [json.loads(line) for line in result.stdout.splitlines()]
            assert len(contexts) == 2
            assert all(item["transaction_read_only"] for item in contexts)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "app.cli", "serve", "--port", str(port)],
        env=env,
        stdout=log,
        stderr=log,
        creationflags=flags,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            assert process.poll() is None, "server exited during startup"
            try:
                response = httpx.get(f"http://127.0.0.1:{port}/health/ready", timeout=1)
                if response.status_code == 200:
                    assert response.json()["read_only"] is True
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        log.seek(0)
        raise AssertionError("server readiness deadline exceeded: " + log.read()[-3500:])
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()
