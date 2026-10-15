"""The demo explains what happened to every record using the service's own permission check."""

from __future__ import annotations

from datetime import UTC, datetime

from agentic_context_service.adapters.opa import PolicyDecision
from agentic_context_service.adapters.opensearch import SearchRequest, is_permitted
from agentic_context_service.demo.explain import explain
from agentic_context_service.demo.scenario import ASSISTANTS, RECORDS, Assistant

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
DOCUMENTS = [record.indexed(NOW) for record in RECORDS]


def _assistant(assistant_id: str) -> Assistant:
    return next(assistant for assistant in ASSISTANTS if assistant.id == assistant_id)


def _decision(
    assistant: Assistant, corpora: tuple[str, ...], classes: tuple[str, ...]
) -> PolicyDecision:
    return PolicyDecision(
        allow=True,
        decision_id="opa:test",
        reason="allowed",
        tenant_id=assistant.tenant_id,
        allowed_corpora=corpora,
        allowed_classifications=classes,
    )


def _by_id(assistant_id: str, corpora: tuple[str, ...], returned: set[str]) -> dict[str, str]:
    assistant = _assistant(assistant_id)
    decision = _decision(assistant, corpora, ("public", "internal", "confidential"))
    outcomes = explain(DOCUMENTS, decision, assistant, frozenset(returned))
    return {outcome.record_id: f"{outcome.status}: {outcome.reason}" for outcome in outcomes}


def test_should_name_the_reason_for_each_record_when_the_pricing_assistant_asks() -> None:
    # Given / When
    outcomes = _by_id(
        "pricing-assistant",
        ("pricing", "product", "approved-decisions"),
        {"NS-100", "NS-100-product", "PROMO-88"},
    )

    # Then
    assert outcomes == {
        "NS-100": "returned: Sent to the assistant.",
        "NS-100-margin": "set_aside: Only for the finance team.",
        "NS-100-product": "returned: Sent to the assistant.",
        "RETURNS-2": "set_aside: Only for the help desk.",
        "PROMO-88": "returned: Sent to the assistant.",
        "PLAN-7": "set_aside: Only for the board.",
        "NS-100-other": "set_aside: Belongs to another shop.",
    }


def test_should_say_a_group_was_not_searched_when_the_assistant_did_not_ask_for_it() -> None:
    # Given / When
    outcomes = _by_id("support-bot", ("product",), {"NS-100-product"})

    # Then
    assert outcomes["PROMO-88"] == "not_searched: Not in the record groups it asked to search."


def test_should_say_allowed_but_unmatched_when_a_visible_record_did_not_match() -> None:
    # Given / When
    outcomes = _by_id("support-bot", ("product", "support", "approved-decisions"), set())

    # Then
    assert outcomes["RETURNS-2"].startswith("no_match: Allowed, but")


def test_should_call_a_record_too_sensitive_when_its_class_is_not_allowed() -> None:
    # Given
    assistant = _assistant("pricing-assistant")
    decision = _decision(assistant, ("pricing", "product", "approved-decisions"), ("public",))

    # When
    outcomes = explain(DOCUMENTS, decision, assistant, frozenset())

    # Then
    ns100 = next(outcome for outcome in outcomes if outcome.record_id == "NS-100")
    assert (ns100.status, ns100.reason) == ("set_aside", "Too sensitive for this job.")


def test_should_mark_everything_not_searched_when_the_request_was_refused() -> None:
    # Given / When
    outcomes = explain(DOCUMENTS, None, _assistant("support-bot"), frozenset())

    # Then
    assert {outcome.status for outcome in outcomes} == {"not_searched"}
    assert outcomes[0].reason == "The request was refused, so nothing was searched."


def test_should_agree_with_the_store_permission_check_for_every_record() -> None:
    # Given
    corpora = ("pricing", "product", "approved-decisions")
    for assistant in ASSISTANTS:
        decision = _decision(assistant, corpora, ("public", "internal", "confidential"))
        request = SearchRequest(
            tenant_id=assistant.tenant_id,
            text="",
            corpora=corpora,
            classifications=decision.allowed_classifications,
            purpose=assistant.purpose,
        )

        # When
        outcomes = explain(DOCUMENTS, decision, assistant, frozenset())

        # Then
        for document, outcome in zip(DOCUMENTS, outcomes, strict=True):
            assert (outcome.status == "no_match") == is_permitted(document, request)
