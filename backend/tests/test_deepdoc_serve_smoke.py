from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_json(url: str, *, timeout_seconds: float = 20.0) -> dict:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
            time.sleep(0.25)

    raise AssertionError(f"Timed out waiting for {url}: {last_error}")


def test_deepdoc_cli_serve_exposes_health_and_capabilities():
    port = _reserve_local_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "src.shared.utils.deepdoc",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        health = _wait_for_json(f"http://127.0.0.1:{port}/health")
        capabilities = _wait_for_json(f"http://127.0.0.1:{port}/capabilities")

        assert health["status"] == "ok"
        assert health["engine"] == "deepdoc"
        assert health["upstream"]["commit"] == "4060cd144003602dd227d8aab2b1dc1b9d740cdc"
        assert "pdf_modes" in capabilities
        assert "vision" in capabilities["pdf_modes"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
