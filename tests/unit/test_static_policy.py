"""The offline policy stand-in gives the same answers as policies/context/authz.rego.

Each case mirrors a test in policies/context/authz_test.rego, so the offline demo cannot
quietly grant more than OPA would.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_context_service.adapters.opa import PolicyDecision, PolicyUnavailableError
from agentic_context_service.testing.policy import PolicyInputError, StaticPolicy

POLICY_DATA = Path(__file__).parents[2] / "policies/context/data.json"
PRICING_NAMESPACE = "demo-retail:development:pricing-analysis:v1:analyst-42:sess:demo"


def _input(
    *,
    request: dict[str, object] | None = None,
    identity: dict[str, object] | None = None,
    workload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "identity": {
            "subject": "analyst-42",
            "tenant_id": "demo-retail",
            "teams": ["pricing"],
            "entitlements": ["pricing-analysis", "memory-management"],
            **(identity or {}),
        },
        "workload": {
            "team_id": "pricing",
            "app_id": "demo-agent",
            "workflow_id": "pricing-analysis",
            "workflow_revision": "v1",
            "agent_id": "demo",
            "environment": "development",
            "cost_center": "oss",
            "headers_verified": True,
            **(workload or {}),
        },
        "request": {
            "operation": "retrieve",
            "purpose": "pricing-analysis",
            "corpora": ["pricing", "restricted-payroll"],
            "classifications": ["internal", "restricted"],
            "namespace": None,
            "source": None,
            **(request or {}),
        },
    }


async def _decide(policy_input: dict[str, object]) -> PolicyDecision:
    return await StaticPolicy.from_file(POLICY_DATA).authorize(policy_input)


@pytest.mark.asyncio
async def test_should_allow_and_narrow_when_request_is_verified_and_entitled() -> None:
    # Given / When
    decision = await _decide(_input())

    # Then
    assert decision.allow
    assert decision.allowed_corpora == ("pricing",)
    assert decision.allowed_classifications == ("internal",)
    assert decision.result_limit == 12
    assert decision.allow_lexical_fallback
    assert decision.decision_id == "opa:demo-retail:pricing-analysis:retrieve"


@pytest.mark.asyncio
async def test_should_return_pricing_facts_only_when_purpose_is_pricing() -> None:
    # Given
    support = _input(
        identity={"entitlements": ["customer-support"]},
        request={"purpose": "customer-support"},
    )

    # When
    pricing_decision = await _decide(_input())
    support_decision = await _decide(support)

    # Then
    assert "source_facts" in pricing_decision.allowed_fields
    assert "source_facts" not in support_decision.allowed_fields


@pytest.mark.asyncio
async def test_should_deny_when_headers_are_not_verified() -> None:
    # Given / When
    decision = await _decide(_input(workload={"headers_verified": False}))

    # Then
    assert not decision.allow


@pytest.mark.asyncio
async def test_should_deny_everything_when_purpose_is_unknown() -> None:
    # Given / When
    decision = await _decide(_input(request={"purpose": "curiosity"}))

    # Then
    assert not decision.allow
    assert decision.reason == "denied"
    assert decision.allowed_corpora == ()
    assert decision.allowed_classifications == ()
    assert decision.allowed_namespaces == ()
    assert decision.result_limit is None
    assert decision.tenant_id == "demo-retail"


@pytest.mark.asyncio
async def test_should_grant_full_persona_scope_when_request_names_no_filters() -> None:
    # Given / When
    decision = await _decide(_input(request={"corpora": [], "classifications": []}))

    # Then
    assert decision.allowed_corpora == ("pricing", "product", "approved-decisions")
    assert decision.allowed_classifications == ("confidential", "internal", "memory", "public")


@pytest.mark.asyncio
async def test_should_allow_own_memory_namespace_when_namespace_is_canonical() -> None:
    # Given
    request = {"operation": "memory.write", "purpose": "memory-management"}

    # When
    decision = await _decide(_input(request={**request, "namespace": PRICING_NAMESPACE}))

    # Then
    assert decision.allow
    assert decision.allowed_namespaces == (PRICING_NAMESPACE,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "namespace",
    [
        "development/other-workflow/v1/analyst-42/sess/demo",
        "demo-retail:development:pricing-analysis:v1:other-user:sess:demo",
    ],
)
async def test_should_grant_no_namespace_when_namespace_is_not_the_callers(
    namespace: str,
) -> None:
    # Given
    request = {"operation": "memory.search", "purpose": "memory-management"}

    # When
    decision = await _decide(_input(request={**request, "namespace": namespace}))

    # Then
    assert decision.allowed_namespaces == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(("source", "allowed"), [("postgresql", True), ("payroll", False)])
async def test_should_check_the_source_when_reading_freshness(source: str, allowed: bool) -> None:
    # Given
    request: dict[str, object] = {"operation": "freshness.read", "source": source}

    # When
    decision = await _decide(_input(request=request))

    # Then
    assert decision.allow is allowed


@pytest.mark.asyncio
async def test_should_disable_lexical_fallback_when_running_in_production() -> None:
    # Given / When
    decision = await _decide(_input(workload={"environment": "production"}))

    # Then
    assert decision.allow
    assert not decision.allow_lexical_fallback


@pytest.mark.asyncio
async def test_should_refuse_input_when_it_does_not_match_the_policy_contract() -> None:
    # Given
    policy = StaticPolicy.from_file(POLICY_DATA)

    # When / Then
    with pytest.raises(PolicyInputError):
        await policy.authorize({"identity": {}})


@pytest.mark.asyncio
async def test_should_report_ready_when_tables_are_loaded() -> None:
    # Given / When / Then
    assert await StaticPolicy.from_file(POLICY_DATA).ready()


@pytest.mark.asyncio
async def test_should_give_no_decision_when_purpose_has_no_collections_and_none_are_named() -> None:
    # Given: restricted-data is an entitlement with no corpora_by_purpose entry. Rego leaves
    # `decision` undefined here, so the real OPA client fails closed.
    policy_input = _input(
        identity={"entitlements": ["restricted-data"]},
        request={"purpose": "restricted-data", "corpora": []},
    )

    # When / Then
    with pytest.raises(PolicyUnavailableError):
        await _decide(policy_input)


@pytest.mark.asyncio
async def test_should_grant_no_collections_when_purpose_has_none_but_some_are_named() -> None:
    # Given
    policy_input = _input(
        identity={"entitlements": ["restricted-data"]},
        request={"purpose": "restricted-data", "corpora": ["pricing"]},
    )

    # When
    decision = await _decide(policy_input)

    # Then
    assert decision.allow
    assert decision.allowed_corpora == ()
