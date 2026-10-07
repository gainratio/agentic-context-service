"""The repository identities this module's gates may run for."""

from __future__ import annotations

from typing import Final

DEFAULT_REPOSITORY: Final = "hseshadr/agentic-context-service"
ALLOWED_REPOSITORIES: Final = (
    DEFAULT_REPOSITORY,
    "gainratio/agentic-context-service",
)


class RepositoryIdentityError(ValueError):
    """The run's repository is not one this module may gate."""


def resolve_repository(repository: str) -> str:
    """Return the run's repository when it is exactly an allowed identity."""
    if repository not in ALLOWED_REPOSITORIES:
        allowed = ", ".join(ALLOWED_REPOSITORIES)
        message = f"{repository!r} is not an allowed repository (expected one of: {allowed})"
        raise RepositoryIdentityError(message)
    return repository


def clone_url(repository: str) -> str:
    """Return the HTTPS clone URL for an allowed repository identity."""
    return f"https://github.com/{resolve_repository(repository)}.git"
