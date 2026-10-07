"""The Dagger gates run only for this repository, owned by hseshadr or gainratio."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = ROOT / ".dagger/src/agentic_context_service_ci/identity.py"
TODAY = "hseshadr/agentic-context-service"
AFTER_TRANSFER = "gainratio/agentic-context-service"


def _identity() -> ModuleType:
    spec = importlib.util.spec_from_file_location("acs_ci_identity", IDENTITY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_allow_list_is_exactly_the_two_owners_of_this_repository() -> None:
    assert _identity().ALLOWED_REPOSITORIES == (TODAY, AFTER_TRANSFER)


def test_default_repository_is_todays_identity() -> None:
    assert _identity().DEFAULT_REPOSITORY == TODAY


@pytest.mark.parametrize("repository", [TODAY, AFTER_TRANSFER])
def test_owned_repository_is_accepted(repository: str) -> None:
    assert _identity().resolve_repository(repository) == repository


@pytest.mark.parametrize("repository", [TODAY, AFTER_TRANSFER])
def test_clone_url_follows_the_accepted_identity(repository: str) -> None:
    assert _identity().clone_url(repository) == f"https://github.com/{repository}.git"


@pytest.mark.parametrize(
    "repository",
    [
        "attacker/agentic-context-service",
        "gainratio/agentic-saga",
        "hseshadr/agentic-context-service-evil",
        "gainratio-evil/agentic-context-service",
        "",
    ],
)
def test_any_other_repository_is_refused(repository: str) -> None:
    identity = _identity()
    with pytest.raises(identity.RepositoryIdentityError, match="not an allowed repository"):
        identity.resolve_repository(repository)
    with pytest.raises(identity.RepositoryIdentityError, match="not an allowed repository"):
        identity.clone_url(repository)
