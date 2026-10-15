"""Smoke test the demo command as a user runs it: a real process on a real port."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parents[2]
STARTUP_SECONDS = 20


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_until_live(base_url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline and process.poll() is None:
        try:
            if httpx.get(f"{base_url}/health/live").status_code == 200:
                return
        except httpx.TransportError:
            time.sleep(0.2)
    raise AssertionError("the demo server did not start")


@pytest.fixture
def demo_url() -> Iterator[str]:
    port = _free_port()
    command = [sys.executable, "-m", "agentic_context_service.demo"]
    process = subprocess.Popen([*command, "--no-browser", "--port", str(port)], cwd=ROOT)
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_live(base_url, process)
        yield base_url
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.integration
def test_should_serve_the_page_and_answer_when_the_demo_command_runs(demo_url: str) -> None:
    # Given / When
    page = httpx.get(f"{demo_url}/demo/")
    answer = httpx.post(
        f"{demo_url}/demo/api/ask",
        json={
            "assistant": "pricing-assistant",
            "question": "What is the discount limit for NS-100?",
            "corpora": ["pricing", "product", "approved-decisions"],
        },
    ).json()

    # Then
    assert page.status_code == 200
    assert "Offline demo" in page.text
    assert answer["response"]["status"] == 200
    assert answer["response"]["body"]["results"][0]["citation"]["record_id"] == "NS-100"
