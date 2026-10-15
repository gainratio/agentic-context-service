"""The README's client example is a real file, runs against the real API, and prints what the
README says it prints. If either drifts, this fails."""

from __future__ import annotations

import re
import runpy
from pathlib import Path

import httpx
import pytest

from agentic_context_service.demo.app import create_demo_app

ROOT = Path(__file__).parents[2]
EXAMPLE = ROOT / "examples/client/ask_the_service.py"
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _section(heading: str) -> str:
    return README.split(f"{heading}\n", 1)[1].split("\n## ", 1)[0]


def test_should_include_the_example_verbatim_when_the_readme_shows_client_code() -> None:
    # Given
    source = EXAMPLE.read_text(encoding="utf-8")

    # When
    blocks = re.findall(r"```python\n(.*?)```", _section("## Use it in your own code"), re.DOTALL)

    # Then
    assert source in blocks


@pytest.mark.asyncio
async def test_should_print_the_documented_answer_when_run_against_the_service(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    example = runpy.run_path(str(EXAMPLE))
    app = create_demo_app(ROOT / "policies/context/data.json")

    # When
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://demo") as client:
        await example["main"](client)
    printed = capsys.readouterr().out

    # Then
    assert printed.startswith("NS-100 discount limit")
    blocks = re.findall(r"```text\n(.*?)```", _section("## Use it in your own code"), re.DOTALL)
    assert printed in blocks
