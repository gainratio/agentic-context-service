"""Suite-wide fixtures."""

from __future__ import annotations

import pytest

from agentic_context_service.config.settings import Settings


@pytest.fixture(autouse=True)
def _ignore_developer_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests configure Settings through the environment only, never a local .env file.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
