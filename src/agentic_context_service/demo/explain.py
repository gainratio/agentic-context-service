"""Say, in plain words, what happened to each record for one question.

Whether a record could be shown is decided by the OpenSearch adapter's own `is_permitted`
check, fed with the policy decision the service used. The reason text only names which of
that check's conditions failed first.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final, Literal

from agentic_context_service.adapters.opa import PolicyDecision
from agentic_context_service.adapters.opensearch import SearchRequest, is_permitted
from agentic_context_service.demo.scenario import JOB_LABELS, Assistant

Status = Literal["returned", "set_aside", "not_searched", "no_match"]
_REFUSED: Final = "The request was refused, so nothing was searched."
_RETURNED: Final = "Sent to the assistant."
_NO_MATCH: Final = "Allowed, but not a close enough match for the question."


@dataclass(frozen=True, slots=True)
class Outcome:
    record_id: str
    status: Status
    reason: str


@dataclass(frozen=True, slots=True)
class _Rule:
    blocks: Callable[[dict[str, Any], SearchRequest], bool]
    status: Status
    reason: Callable[[dict[str, Any]], str]


def _readers(document: dict[str, Any]) -> str:
    purposes = document["governance"]["allowed_purposes"]
    return f"Only for {' and '.join(JOB_LABELS.get(p, p) for p in purposes)}."


_RULES: Final = (
    _Rule(
        lambda doc, req: doc["tenant_id"] != req.tenant_id,
        "set_aside",
        lambda _doc: "Belongs to another shop.",
    ),
    _Rule(
        lambda doc, req: req.purpose not in doc["governance"]["allowed_purposes"],
        "set_aside",
        _readers,
    ),
    _Rule(
        lambda doc, req: doc["governance"]["classification"] not in req.classifications,
        "set_aside",
        lambda _doc: "Too sensitive for this job.",
    ),
    _Rule(
        lambda doc, req: doc["domain"] not in req.corpora,
        "not_searched",
        lambda _doc: "Not in the record groups it asked to search.",
    ),
)


def explain(
    documents: Iterable[dict[str, Any]],
    decision: PolicyDecision | None,
    assistant: Assistant,
    returned: frozenset[str],
) -> list[Outcome]:
    """One outcome per record. `decision` is None when the service refused the request."""
    if decision is None:
        return [Outcome(doc["document_id"], "not_searched", _REFUSED) for doc in documents]
    request = SearchRequest(
        tenant_id=assistant.tenant_id,
        text="",
        corpora=decision.allowed_corpora,
        classifications=decision.allowed_classifications,
        purpose=assistant.purpose,
    )
    return [_outcome(doc, request, returned) for doc in documents]


def _outcome(document: dict[str, Any], request: SearchRequest, returned: frozenset[str]) -> Outcome:
    record_id = str(document["document_id"])
    if record_id in returned:
        return Outcome(record_id, "returned", _RETURNED)
    if is_permitted(document, request):
        return Outcome(record_id, "no_match", _NO_MATCH)
    rule = next(rule for rule in _RULES if rule.blocks(document, request))
    return Outcome(record_id, rule.status, rule.reason(document))
