from __future__ import annotations

import ast
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
SIGNING_KEY = "ACS_SIGNING_" + "SECRET"


def test_required_oss_files_exist() -> None:
    required = {
        ".env.example",
        "AGENTS.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "docs/architecture/index.html",
        "docs/specification.md",
        "docs/threat-model/README.md",
        "packages/contracts/openapi.yaml",
    }
    missing = sorted(path for path in required if not (ROOT / path).is_file())
    assert not missing, f"missing required OSS artifacts: {missing}"


def test_makefile_is_only_a_thin_poe_wrapper() -> None:
    text = (ROOT / "Makefile").read_text()
    targets = {
        "bootstrap",
        "format",
        "lint",
        "unit",
        "integration",
        "bdd",
        "security",
        "eval",
        "up",
        "seed",
        "demo",
        "down",
        "clean",
        "verify",
    }
    assert targets.issubset(set(re.findall(r"\b[a-z]+", text.splitlines()[0])))
    assert text.count("uv run poe") == 1


def test_example_environment_contains_no_secret() -> None:
    values = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    assert values
    assert all("sk-" not in value and "ghp_" not in value for value in values.values())
    assert values[SIGNING_KEY] == "replace-with-at-least-32-characters"


def test_openapi_has_every_required_endpoint_and_no_raw_dsl() -> None:
    document = yaml.safe_load((ROOT / "packages/contracts/openapi.yaml").read_text())
    required = {
        "/v1/context:retrieve",
        "/v1/context:batchRetrieve",
        "/v1/memories",
        "/v1/memories:search",
        "/v1/memories/{id}",
        "/v1/feedback",
        "/v1/sources/{source}/freshness",
        "/health/live",
        "/health/ready",
    }
    assert required.issubset(document["paths"])
    serialized = str(document).lower()
    assert "opensearch_dsl" not in serialized
    assert "raw_dsl" not in serialized


def test_local_indexer_consumes_every_declared_showcase_cdc_topic() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose/docker-compose.yml").read_text())
    indexer_environment = compose["services"]["indexer"]["environment"]

    assert indexer_environment["ACS_KAFKA_TOPICS"] == (
        "catalog.public.pricing_rules,fulfillment.public.fulfillment_rules"
    )


def test_inward_layers_import_no_vendor_frameworks() -> None:
    forbidden = {
        "fastapi",
        "pydantic",
        "opensearchpy",
        "aiokafka",
        "httpx",
        "langgraph",
        "sentence_transformers",
    }
    files = [
        *ROOT.glob("src/agentic_context_service/domain/**/*.py"),
        *ROOT.glob("src/agentic_context_service/application/**/*.py"),
        *ROOT.glob("src/agentic_context_service/ports/**/*.py"),
    ]
    violations: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text())
        imports = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        if imports & forbidden:
            violations.append(f"{path.relative_to(ROOT)}: {sorted(imports & forbidden)}")
    assert not violations, "inward dependency violations:\n" + "\n".join(violations)


def test_personal_project_has_no_gap_inc_reference() -> None:
    prohibited = "gap" + " inc"
    text_paths = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and ".venv" not in path.parts
        and path.suffix in {"", ".md", ".py", ".toml", ".yaml", ".yml", ".json", ".rego"}
    ]
    offenders = [
        str(path.relative_to(ROOT))
        for path in text_paths
        if prohibited in path.read_text(errors="ignore").lower()
    ]
    assert not offenders, f"personal project contains prohibited employer reference: {offenders}"


def test_project_is_mit_licensed_everywhere_it_states_its_license() -> None:
    license_text = (ROOT / "LICENSE").read_text()
    assert license_text.startswith("MIT License\n\nCopyright (c) 2026 Harish Seshadri\n")
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'license = "MIT"' in pyproject
    assert "License :: OSI Approved :: MIT License" in pyproject
    openapi = yaml.safe_load((ROOT / "packages/contracts/openapi.yaml").read_text())
    assert openapi["info"]["license"] == {"name": "MIT", "identifier": "MIT"}
    assert "License: MIT" in (ROOT / "docs/specification.md").read_text()
    assert "license-MIT" in (ROOT / "README.md").read_text()
    own_docs = ("README.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md", "docs/specification.md")
    for path in (*own_docs, "pyproject.toml", "packages/contracts/openapi.yaml"):
        assert "apache" not in (ROOT / path).read_text().lower(), path


# gainratio/ci (moved from hseshadr/ci, same history) main at #70; must stay at or after #46
# (dd19871: greenMain tolerates GitHub's rerun created_at skew). A pin below it blocks
# releases whenever main CI is re-run.
CI_MODULE_PIN = "528eaec76121b75810c58bab610d9f2064b95227"


def test_ci_modules_pinned_to_reviewed_commit() -> None:
    deps = json.loads((ROOT / "dagger.json").read_text())["dependencies"]
    # GitHub redirects git fetches for moved repos today, but not forever: pin the new owner.
    assert not [d for d in deps if "github.com/hseshadr/ci/" in d["source"]]
    ci_deps = {d["name"]: d for d in deps if "github.com/gainratio/ci/" in d["source"]}
    assert set(ci_deps) == {"foundation", "python-package"}
    for dep in ci_deps.values():
        assert dep["source"].endswith(f"@{CI_MODULE_PIN}"), dep
        assert dep["pin"] == CI_MODULE_PIN, dep


def _compose_services() -> dict[str, dict[str, object]]:
    compose = yaml.safe_load((ROOT / "deploy/compose/docker-compose.yml").read_text())
    services: dict[str, dict[str, object]] = compose["services"]
    return services


def test_local_stack_runs_natively_on_every_host_architecture() -> None:
    # A platform pin forces emulation on Apple silicon; amd64 OPA segfaults there.
    pinned = sorted(name for name, svc in _compose_services().items() if "platform" in svc)

    assert not pinned, f"services pinned to one platform: {pinned}"


def test_local_opa_uses_the_multi_arch_static_image() -> None:
    # Only OPA's "-static" tags publish linux/arm64; the plain tag is amd64-only.
    opa = _compose_services()["opa"]

    assert opa["image"] == "openpolicyagent/opa:1.8.0-static"


def test_local_opa_healthcheck_execs_the_opa_binary_without_a_shell() -> None:
    healthcheck = _compose_services()["opa"]["healthcheck"]
    assert isinstance(healthcheck, dict)

    assert healthcheck["test"][:2] == ["CMD", "/opa"]


def test_local_stack_images_avoid_the_retired_personal_mirror() -> None:
    images = [str(svc["image"]) for svc in _compose_services().values() if "image" in svc]

    assert images
    assert not [image for image in images if "hseshadr" in image]


def test_make_targets_ignore_a_foreign_active_virtualenv() -> None:
    # uv warns when VIRTUAL_ENV points at another project's venv; make must not inherit it.
    makefile_lines = (ROOT / "Makefile").read_text().splitlines()

    assert "unexport VIRTUAL_ENV" in makefile_lines


def _create_memory_field(*path: str) -> object:
    node: object = yaml.safe_load((ROOT / "packages/contracts/openapi.yaml").read_text())
    for key in ("paths", "/v1/memories", "post", *path):
        assert isinstance(node, dict), f"openapi createMemory has no {key!r}"
        node = node[key]
    return node


def test_openapi_create_memory_example_is_accepted_by_the_api() -> None:
    # The API rejects a past expiry, so a dated example must stay in the future.
    content = ("requestBody", "content", "application/json", "example", "expires_at")
    expires_at = datetime.fromisoformat(str(_create_memory_field(*content)))

    assert expires_at > datetime.now(UTC)


def test_openapi_documents_the_past_expiry_rejection() -> None:
    description = _create_memory_field("responses", "400", "description")

    assert "expires_at" in str(description)
