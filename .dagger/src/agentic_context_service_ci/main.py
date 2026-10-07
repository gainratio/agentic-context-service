"""Exact-source quality and security gates for Agentic Context Service."""

from __future__ import annotations

from typing import Final, Self

import dagger
from dagger import check, dag, field, function, object_type

from .identity import clone_url, resolve_repository

PYTHON_IMAGE: Final = (
    "python:3.13.14-bookworm@sha256:"
    "8b9a8b28d9cc221c6ab5d40e9cfcd99429959f6a8f5171612a99147975ab043f"
)
UV_IMAGE: Final = (
    "ghcr.io/astral-sh/uv:0.11.32@sha256:"
    "df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c"
)
NODE_IMAGE: Final = (
    "node:24.16.0-bookworm-slim@sha256:"
    "2c87ef9bd3c6a3bd4b472b4bec2ce9d16354b0c574f736c476489d09f560a203"
)
SOURCE_ROOT: Final = "/src"
LOCK_INPUTS: Final = ("pyproject.toml", "uv.lock")
NODE_LOCK_INPUTS: Final = ("package.json", "package-lock.json")
SBOM_PATH: Final = "/src/reports/sbom.cdx.json"
SOURCE_IGNORE_PATTERNS: Final = [
    ".git",
    ".env",
    "**/.env",
    ".env.*",
    "**/.env.*",
    "!.env.example",
    "!**/.env.example",
    "**/.netrc",
    "**/.npmrc",
    "**/.pypirc",
    "**/*.key",
    "**/*.jks",
    "**/*.p12",
    "**/*.pfx",
    "**/*.pem",
    "**/*.tfstate",
    "**/*.tfvars",
    "**/*credentials*",
    "**/*secret*",
    ".artifacts",
    ".dagger/.venv",
    ".dagger/sdk",
    ".coverage*",
    "**/.coverage*",
    ".hypothesis",
    "**/.hypothesis",
    ".mypy_cache",
    "**/.mypy_cache",
    ".pytest_cache",
    "**/.pytest_cache",
    ".ruff_cache",
    "**/.ruff_cache",
    "**/__pycache__",
    ".venv",
    "build",
    "dist",
]


async def _guard(
    source: dagger.Directory,
    commit_sha: str,
    repository: str,
) -> None:
    guarded = dag.foundation().guard(
        source=source,
        repository=repository,
        commit_sha=commit_sha,
    )
    await guarded.sync()


async def _exact_source(
    source: dagger.Directory,
    commit_sha: str,
    repository: str,
) -> dagger.Directory:
    verified = resolve_repository(repository)
    await _guard(source, commit_sha, verified)
    remote = dag.git(clone_url(verified))
    return remote.commit(commit_sha).tree(depth=0, include_tags=True)


def _dependencies(source: dagger.Directory) -> dagger.Container:
    uv = dag.container().from_(UV_IMAGE).file("/uv")
    base = dag.container().from_(PYTHON_IMAGE).with_file("/usr/local/bin/uv", uv)
    locked = base.with_directory(SOURCE_ROOT, source, include=list(LOCK_INPUTS))
    locked = locked.with_workdir(SOURCE_ROOT).with_env_variable(
        "UV_PROJECT_ENVIRONMENT", "/opt/venv"
    )
    return locked.with_exec(
        ["uv", "sync", "--frozen", "--all-groups", "--all-extras", "--no-install-project"]
    )


def _project(source: dagger.Directory) -> dagger.Container:
    complete = _dependencies(source).with_directory(SOURCE_ROOT, source).with_workdir(SOURCE_ROOT)
    # `_dependencies` syncs with --no-install-project, so the project itself is built
    # here. Build isolation would re-resolve `build-system.requires` against index
    # metadata the lockfile path never cached, which --offline cannot reach:
    # "hatchling was not found in the cache". hatchling is already installed from
    # uv.lock, so skip isolation. A wheel rather than an editable install then avoids
    # `editables`, which uv.lock does not carry at all.
    return complete.with_exec(
        [
            "uv",
            "sync",
            "--frozen",
            "--all-groups",
            "--all-extras",
            "--offline",
            "--no-build-isolation",
            "--no-editable",
        ]
    )


def _security_evidence(source: dagger.Directory) -> dagger.Container:
    """Build the SBOM and retain the existing static security proof in Dagger."""
    return (
        _project(source)
        .with_exec(["uv", "run", "bandit", "-q", "-r", "src", "scripts"])
        .with_exec(
            [
                "uv",
                "run",
                "pip-audit",
                "--format",
                "cyclonedx-json",
                "--output",
                SBOM_PATH,
            ]
        )
    )


def _showcase(source: dagger.Directory) -> dagger.Container:
    """Run the repository's real Playwright Chromium showcase path."""
    node = dag.container().from_(NODE_IMAGE).directory("/usr/local")
    locked = _project(source).with_directory("/usr/local", node)
    locked = locked.with_directory(SOURCE_ROOT, source, include=list(NODE_LOCK_INPUTS))
    installed = locked.with_env_variable("CI", "1").with_exec(["npm", "ci"])
    return installed.with_exec(["npm", "run", "install:browser", "--", "--with-deps"]).with_exec(
        ["npm", "run", "test:ui"]
    )


@object_type
class AgenticContextService:
    """Expose only the canonical CI and security operations."""

    source: dagger.Directory = field()

    @classmethod
    def create(cls, workspace: dagger.Workspace) -> Self:
        """Own the engine-detected workspace instead of accepting caller source."""
        instance = cls.__new__(cls)
        instance.source = workspace.directory("/", exclude=SOURCE_IGNORE_PATTERNS)
        return instance

    @function
    @check
    async def ci(
        self,
        commit_sha: str,
        repository: str,
    ) -> str:
        """Resolve the guarded commit once and run the repository-owned gate."""
        verified = await _exact_source(self.source, commit_sha, repository)
        proof = _project(verified).with_exec(
            ["uv", "run", "python", "-m", "scripts.validate_contracts"]
        )
        await proof.with_exec(["uv", "run", "poe", "verify"]).sync()
        return "Agentic Context Service canonical Dagger gate passed"

    @function
    async def security(
        self,
        commit_sha: str,
        repository: str,
    ) -> str:
        """Run guarded locked dependency and source security checks."""
        verified = await _exact_source(self.source, commit_sha, repository)
        audit = dag.python_package().dependency_audit(
            source=verified,
            repository=repository,
            commit_sha=commit_sha,
        )
        await audit.sync()
        await (
            _project(verified)
            .with_exec(["uv", "run", "bandit", "-q", "-r", "src", "scripts"])
            .sync()
        )
        return "Agentic Context Service dependency and source audits passed"

    @function
    async def security_evidence(
        self,
        commit_sha: str,
        repository: str,
    ) -> str:
        """Generate a CycloneDX SBOM and run the source security scan."""
        verified = await _exact_source(self.source, commit_sha, repository)
        evidence = await _security_evidence(verified).sync()
        await evidence.file(SBOM_PATH).contents()
        return "Agentic Context Service security evidence passed"

    @function
    async def ui(
        self,
        commit_sha: str,
        repository: str,
    ) -> str:
        """Exercise the user-facing showcase with real Chromium."""
        verified = await _exact_source(self.source, commit_sha, repository)
        await _showcase(verified).sync()
        return "Agentic Context Service Chromium showcase passed"
