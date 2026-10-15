"""An in-process stand-in for OPA, for the offline demo and for consumer tests.

It reads the same tables OPA reads (`policies/context/data.json`) and applies the rules in
`policies/context/authz.rego`. tests/unit/test_static_policy.py replays the Rego test cases
against it. The full stack always asks the real OPA server instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from agentic_context_service.adapters.opa import PolicyDecision

_ENVIRONMENTS: Final = frozenset({"development", "test", "staging", "production"})
_RESULT_LIMIT: Final = 12
_NAMESPACE_PARTS: Final = 7
_FRESHNESS: Final = "freshness.read"


class PolicyInputError(ValueError):
    """The policy input does not match the contract the service sends to OPA."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyTables(_Strict):
    """The data document OPA loads beside the Rego rules."""

    operations: tuple[str, ...]
    corpora_by_purpose: dict[str, tuple[str, ...]]
    sources_by_purpose: dict[str, tuple[str, ...]]
    classifications_by_entitlement: dict[str, tuple[str, ...]]
    response_fields_by_purpose: dict[str, tuple[str, ...]]


class _Identity(_Strict):
    subject: str
    tenant_id: str
    teams: tuple[str, ...]
    entitlements: tuple[str, ...]


class _Workload(_Strict):
    team_id: str
    app_id: str
    workflow_id: str
    workflow_revision: str
    agent_id: str
    environment: str
    cost_center: str
    headers_verified: bool


class _Request(_Strict):
    operation: str
    purpose: str
    corpora: tuple[str, ...]
    classifications: tuple[str, ...]
    namespace: str | None
    source: str | None = None


class _PolicyInput(_Strict):
    identity: _Identity
    workload: _Workload
    request: _Request


class StaticPolicy:
    """Answer authorization questions from the OPA data tables, without an OPA server."""

    def __init__(self, tables: PolicyTables) -> None:
        self._tables = tables

    @classmethod
    def from_file(cls, path: Path) -> StaticPolicy:
        """Load the tables from OPA's data file."""
        return cls(PolicyTables.model_validate_json(path.read_text(encoding="utf-8")))

    async def authorize(self, policy_input: dict[str, Any]) -> PolicyDecision:
        """Return the decision OPA's `decision` rule would return for this input."""
        try:
            parsed = _PolicyInput.model_validate(policy_input)
        except ValidationError as error:
            raise PolicyInputError("policy input does not match the OPA contract") from error
        return self._decide(parsed, allow=self._allows(parsed))

    async def ready(self) -> bool:
        """The tables are loaded in memory, so the policy is always ready."""
        return True

    def _allows(self, given: _PolicyInput) -> bool:
        return all(
            (
                given.identity.subject != "" and given.identity.tenant_id != "",
                _valid_workload(given.workload),
                given.request.purpose in given.identity.entitlements,
                given.request.operation in self._tables.operations,
                self._source_allowed(given.request),
            )
        )

    def _source_allowed(self, request: _Request) -> bool:
        if request.operation != _FRESHNESS:
            return True
        return request.source in self._tables.sources_by_purpose.get(request.purpose, ())

    def _decide(self, given: _PolicyInput, *, allow: bool) -> PolicyDecision:
        return self._granted(given) if allow else self._denied(given)

    def _denied(self, given: _PolicyInput) -> PolicyDecision:
        return PolicyDecision(
            allow=False,
            decision_id=_decision_id(given),
            reason="denied",
            tenant_id=given.identity.tenant_id,
            allowed_fields=self._fields(given.request),
        )

    def _granted(self, given: _PolicyInput) -> PolicyDecision:
        return PolicyDecision(
            allow=True,
            decision_id=_decision_id(given),
            reason="allowed",
            tenant_id=given.identity.tenant_id,
            allowed_corpora=self._corpora(given.request),
            allowed_classifications=self._classifications(given),
            allowed_fields=self._fields(given.request),
            allowed_namespaces=_namespaces(given),
            result_limit=_RESULT_LIMIT,
            allow_lexical_fallback=given.workload.environment != "production",
        )

    def _fields(self, request: _Request) -> tuple[str, ...]:
        return self._tables.response_fields_by_purpose.get(request.purpose, ())

    def _corpora(self, request: _Request) -> tuple[str, ...]:
        permitted = self._tables.corpora_by_purpose.get(request.purpose, ())
        return _narrow(request.corpora, permitted)

    def _classifications(self, given: _PolicyInput) -> tuple[str, ...]:
        by_entitlement = self._tables.classifications_by_entitlement
        persona = sorted(
            {c for e in given.identity.entitlements for c in by_entitlement.get(e, ())}
        )
        return _narrow(given.request.classifications, tuple(persona))


def _decision_id(given: _PolicyInput) -> str:
    identity, workload, request = given.identity, given.workload, given.request
    return f"opa:{identity.tenant_id}:{workload.workflow_id}:{request.operation}"


def _narrow(requested: tuple[str, ...], permitted: tuple[str, ...]) -> tuple[str, ...]:
    """An empty request means "everything permitted"; otherwise keep only permitted items."""
    if not requested:
        return permitted
    return tuple(item for item in requested if item in permitted)


def _valid_workload(workload: _Workload) -> bool:
    return all(
        (
            workload.headers_verified,
            workload.environment in _ENVIRONMENTS,
            workload.workflow_id != "",
            workload.workflow_revision != "",
        )
    )


def _namespaces(given: _PolicyInput) -> tuple[str, ...]:
    namespace = given.request.namespace
    if namespace is None or not _valid_namespace(namespace, given):
        return ()
    return (namespace,)


def _valid_namespace(namespace: str, given: _PolicyInput) -> bool:
    parts = namespace.split(":")
    if len(parts) != _NAMESPACE_PARTS:
        return False
    workload = given.workload
    expected = (given.identity.tenant_id, workload.environment, workload.workflow_id)
    return all(
        (
            tuple(parts[:3]) == expected,
            parts[3] == workload.workflow_revision,
            parts[4] in {"_", given.identity.subject},
            parts[5] != "",
            parts[6] in {"_", workload.agent_id},
        )
    )
