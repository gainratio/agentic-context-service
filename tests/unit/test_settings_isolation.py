"""The suite must not depend on a developer's local .env file."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_context_service.config.settings import Settings


def test_settings_ignore_a_dotenv_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The quickstart copies .env.example to .env; tests must still see only their own env.
    (tmp_path / ".env").write_text("ACS_DEMO_TOKEN=from-a-developer-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ACS_SIGNING_SECRET", "x" * 32)
    monkeypatch.delenv("ACS_DEMO_TOKEN", raising=False)

    assert Settings().demo_token is None
