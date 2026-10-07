from __future__ import annotations

import ast
from pathlib import Path
from typing import cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / ".dagger/src/agentic_context_service_ci/main.py"
WORKFLOWS = ROOT / ".github/workflows"
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
DAGGER_ACTION = "dagger/dagger-for-github@27b130bf0f79a7f6fbbbe0fbca6760dc9bb40a77"
EXPECTED_INGRESS = {
    "dagger.yml": "ci",
    "dagger-security.yml": "security",
    "security-evidence.yml": "security-evidence",
    "ui.yml": "ui",
}


def _tree(source: str | None = None) -> ast.Module:
    return ast.parse(MODULE.read_text() if source is None else source)


def _adapter(source: str | None = None) -> ast.ClassDef:
    classes = [
        node
        for node in _tree(source).body
        if isinstance(node, ast.ClassDef) and node.name == "AgenticContextService"
    ]
    assert len(classes) == 1
    return classes[0]


def _decorator_name(node: ast.expr) -> str:
    value = node.func if isinstance(node, ast.Call) else node
    return value.id if isinstance(value, ast.Name) else getattr(value, "attr", "")


def _annotation(node: ast.arg) -> str:
    assert node.annotation is not None
    return ast.unparse(node.annotation)


def _public_methods(source: str | None = None) -> tuple[ast.AsyncFunctionDef, ...]:
    return tuple(
        member
        for member in _adapter(source).body
        if isinstance(member, ast.AsyncFunctionDef)
        and "function" in {_decorator_name(item) for item in member.decorator_list}
    )


def _assert_module_owned_source(source: str) -> None:
    adapter = _adapter(source)
    fields = [ast.unparse(node) for node in adapter.body if isinstance(node, ast.AnnAssign)]
    assert fields == ["source: dagger.Directory = field()"]
    constructors = [
        node for node in adapter.body if isinstance(node, ast.FunctionDef) and node.name == "create"
    ]
    assert len(constructors) == 1
    constructor = constructors[0]
    assert "classmethod" in {_decorator_name(item) for item in constructor.decorator_list}
    assert [(item.arg, _annotation(item)) for item in constructor.args.args[1:]] == [
        ("workspace", "dagger.Workspace")
    ]
    assert "workspace.directory('/', exclude=SOURCE_IGNORE_PATTERNS)" in ast.unparse(constructor)


def _assert_closed_public_schema(source: str) -> None:
    methods = _public_methods(source)
    assert tuple(method.name for method in methods) == (
        "ci",
        "security",
        "security_evidence",
        "ui",
    )
    for method in methods:
        arguments = (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs)
        public = tuple(item for item in arguments if item.arg != "self")
        assert [(item.arg, _annotation(item)) for item in public] == [
            ("commit_sha", "str"),
            ("repository", "str"),
        ]
        assert not method.args.vararg
        assert not method.args.kwarg
        assert not method.args.defaults, "every gate input is required; no stale default owner"
        assert method.returns is not None
        assert ast.unparse(method.returns) == "str"
        body = ast.unparse(method)
        assert "_exact_source(self.source, commit_sha, repository)" in body


def _workflow_steps(name: str, source: str | None = None) -> list[dict[str, object]]:
    text = (WORKFLOWS / name).read_text() if source is None else source
    document = cast(dict[str, object], yaml.safe_load(text))
    jobs = cast(dict[str, object], document["jobs"])
    assert len(jobs) == 1
    job = cast(dict[str, object], next(iter(jobs.values())))
    return cast(list[dict[str, object]], job["steps"])


def _function_body(name: str) -> str:
    functions = [
        node
        for node in _tree().body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert len(functions) == 1
    return ast.unparse(functions[0])


def _assert_thin_workflow(name: str, source: str | None = None) -> None:
    steps = _workflow_steps(name, source)
    assert len(steps) == 2, "workflow must remain checkout followed by one Dagger call"
    checkout, dagger = steps
    assert checkout["uses"] == CHECKOUT
    assert checkout["with"] == {
        "fetch-depth": 0,
        "ref": "${{ github.sha }}",
        "persist-credentials": False,
    }
    assert dagger["uses"] == DAGGER_ACTION
    assert "run" not in checkout and "run" not in dagger
    assert dagger.get("with") == {
        "version": "0.21.8",
        "verb": "call",
        "args": (
            f"{EXPECTED_INGRESS[name]} --commit-sha=${{{{ github.sha }}}}"
            " --repository=${{ github.repository }}"
        ),
    }


def test_module_owns_the_filtered_engine_workspace_source() -> None:
    _assert_module_owned_source(MODULE.read_text())


def test_public_dagger_api_is_closed_and_typed() -> None:
    _assert_closed_public_schema(MODULE.read_text())


def test_security_evidence_keeps_the_static_scan_and_cyclonedx_sbom() -> None:
    body = _function_body("_security_evidence")
    for marker in ("_project(source)", "bandit", "pip-audit", "cyclonedx-json", "SBOM_PATH"):
        assert marker in body


def test_ui_keeps_the_real_locked_chromium_showcase_path() -> None:
    body = _function_body("_showcase")
    for marker in (
        "NODE_IMAGE",
        "_project(source)",
        "NODE_LOCK_INPUTS",
        "with_env_variable('CI', '1')",
        "npm', 'ci",
        "install:browser",
        "--with-deps",
        "test:ui",
    ):
        assert marker in body


@pytest.mark.parametrize("name", tuple(EXPECTED_INGRESS))
def test_workflow_is_only_checkout_then_typed_dagger(name: str) -> None:
    _assert_thin_workflow(name)


def test_contract_rejects_the_legacy_caller_supplied_directory() -> None:
    source = MODULE.read_text().replace(
        "async def ci(\n        self,\n",
        "async def ci(\n        self,\n        source: dagger.Directory,\n",
        1,
    )
    assert source != MODULE.read_text()
    with pytest.raises(AssertionError):
        _assert_closed_public_schema(source)


def test_contract_rejects_the_legacy_raw_shell_ingress() -> None:
    workflow = (
        (WORKFLOWS / "dagger.yml")
        .read_text()
        .replace(
            "      - uses: dagger/dagger-for-github@",
            "      - run: uv run poe verify\n      - uses: dagger/dagger-for-github@",
            1,
        )
    )
    assert workflow != (WORKFLOWS / "dagger.yml").read_text()
    with pytest.raises(AssertionError, match="checkout followed by one Dagger call"):
        _assert_thin_workflow("dagger.yml", workflow)


def test_guard_and_clone_use_the_resolved_run_identity() -> None:
    body = _function_body("_exact_source")
    assert "resolve_repository(repository)" in body
    assert "_guard(source, commit_sha, verified)" in body
    assert "dag.git(clone_url(verified))" in body
    assert "repository=repository" in _function_body("_guard")
    assert "REPOSITORY_URL" not in MODULE.read_text()


def test_contract_rejects_a_workflow_that_drops_the_run_identity() -> None:
    workflow = (
        (WORKFLOWS / "dagger.yml")
        .read_text()
        .replace(" --repository=${{ github.repository }}", "", 1)
    )
    assert workflow != (WORKFLOWS / "dagger.yml").read_text()
    with pytest.raises(AssertionError):
        _assert_thin_workflow("dagger.yml", workflow)


def test_contract_rejects_a_non_dagger_workflow() -> None:
    workflow = (WORKFLOWS / "ui.yml").read_text().replace(DAGGER_ACTION, CHECKOUT, 1)
    assert workflow != (WORKFLOWS / "ui.yml").read_text()
    with pytest.raises(AssertionError):
        _assert_thin_workflow("ui.yml", workflow)
