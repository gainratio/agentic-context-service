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
OPA_IMAGE: Final = (
    "openpolicyagent/opa:1.8.0-static@sha256:"
    "3c350b0f3130e71000c43c859e1479d8bb9c693442e7e5180e59026b61c068a1"
)
OPA_PARITY_TEST: Final = "tests/integration/test_policy_parity.py"
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


def _opa(source: dagger.Directory) -> dagger.Container:
    return (
        dag.container().from_(OPA_IMAGE).with_directory("/policies", source.directory("policies"))
    )


def _rego_tests(source: dagger.Directory) -> dagger.Container:
    """Run policies/context/authz_test.rego with the same OPA build the stack uses."""
    return _opa(source).with_exec(["/opa", "test", "/policies", "-v"])


def _policy_parity(source: dagger.Directory) -> dagger.Container:
    """Prove the offline StaticPolicy answers exactly like a real OPA server."""
    server = (
        _opa(source)
        .with_exposed_port(8181)
        .as_service(args=["/opa", "run", "--server", "--addr=0.0.0.0:8181", "/policies"])
    )
    return (
        _project(source)
        .with_service_binding("opa", server)
        .with_env_variable("ACS_OPA_PARITY_URL", "http://opa:8181")
        .with_exec(
            ["uv", "run", "pytest", OPA_PARITY_TEST, "-m", "integration", "--force-enable-socket"]
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
        await _rego_tests(verified).sync()
        await _policy_parity(verified).sync()
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
