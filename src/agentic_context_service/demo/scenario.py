"""The made-up company, its records, and its AI assistants used by the offline demo.

Demo Retail sells trail shoes and runs two assistants: one for its pricing team and one for
customer support. A second company, Other Retailer, uses the same service. All data is
synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from agentic_context_service.api.request_context import AuthenticatedPrincipal

# Signs requests between the demo's built-in gateway and the API. Demo only; never reuse it.
DEMO_SIGNING_KEY: Final = b"offline-demo-signing-key-not-for-production"
DEMO_RETAIL: Final = "demo-retail"
OTHER_RETAILER: Final = "other-retailer"
PRICING: Final = "pricing-analysis"
SUPPORT: Final = "customer-support"


@dataclass(frozen=True, slots=True)
class Assistant:
    """One AI assistant: who it works for, its job (purpose), and what it normally searches."""

    id: str
    label: str
    company: str
    tenant_id: str
    bearer: str
    team: str
    workflow: str
    purpose: str
    corpora: tuple[str, ...]

    def principal(self) -> AuthenticatedPrincipal:
        """The identity the service trusts once this assistant's token is checked."""
        return AuthenticatedPrincipal(self.id, self.tenant_id, (self.team,), (self.purpose,))


@dataclass(frozen=True, slots=True)
class Record:
    """One row from a company database, as the indexer would store it."""

    record_id: str
    tenant_id: str
    corpus: str
    title: str
    text: str
    classification: str
    purposes: tuple[str, ...]
    uri: str
    version: str
    age: timedelta

    def indexed(self, now: datetime) -> dict[str, Any]:
        """The document shape the indexer writes to OpenSearch."""
        updated = (now - self.age).isoformat()
        system, resource = self.uri.removeprefix("postgres://").split("/")[:2]
        return {
            "document_id": self.record_id,
            "chunk_id": f"{self.record_id}#0",
            "tenant_id": self.tenant_id,
            "domain": self.corpus,
            "entity_type": resource,
            "title": self.title,
            "content": self.text,
            "keywords": [self.record_id],
            "source": _source(system, resource, self),
            "validity": {"source_updated_at": updated, "indexed_at": updated, "is_deleted": False},
            "governance": _governance(self),
            "trust_class": "verified",
        }


@dataclass(frozen=True, slots=True)
class Example:
    """A ready-made question for the page's example buttons."""

    label: str
    assistant: str
    question: str
    corpora: tuple[str, ...]
    expect: str


def _source(system: str, resource: str, record: Record) -> dict[str, str]:
    return {
        "system": system,
        "resource": resource,
        "record_id": record.record_id,
        "uri": record.uri,
        "version": record.version,
    }


def _governance(record: Record) -> dict[str, Any]:
    return {
        "classification": record.classification,
        "policy_tags": [],
        "allowed_purposes": list(record.purposes),
        "region": "US",
        "retention_class": "R1",
    }


PRICING_CORPORA: Final = ("pricing", "product", "approved-decisions")
SUPPORT_CORPORA: Final = ("product", "support", "approved-decisions")

ASSISTANTS: Final = (
    Assistant(
        "pricing-assistant", "Pricing assistant", "Demo Retail", DEMO_RETAIL,
        "pricing-assistant-token", "pricing", "price-check", PRICING, PRICING_CORPORA,
    ),
    Assistant(
        "support-bot", "Customer support chatbot", "Demo Retail", DEMO_RETAIL,
        "support-bot-token", "support", "customer-chat", SUPPORT, SUPPORT_CORPORA,
    ),
    Assistant(
        "other-company-pricing", "Other Retailer's pricing assistant", "Other Retailer",
        OTHER_RETAILER, "other-retailer-token", "pricing", "price-check", PRICING,
        PRICING_CORPORA,
    ),
)  # fmt: skip

_HOUR: Final = timedelta(hours=1)
_DAY: Final = timedelta(days=1)

RECORDS: Final = (
    Record(
        "NS-100", DEMO_RETAIL, "pricing", "NS-100 discount limit",
        "NS-100 discount limit: at most 20% off list price without pricing-lead approval.",
        "internal", (PRICING,), "postgres://catalog/pricing_rules/NS-100", "7", 2 * _HOUR,
    ),
    Record(
        "NS-100-margin", DEMO_RETAIL, "pricing", "NS-100 margin target",
        "NS-100 target margin is 41%. Finance reviews any discount that takes it below 35%.",
        "confidential", ("finance-review",), "postgres://finance/margins/NS-100-margin", "3",
        3 * _DAY,
    ),
    Record(
        "NS-100-product", DEMO_RETAIL, "product", "NS-100 trail running shoe",
        "NS-100 is a waterproof trail running shoe, sizes 6 to 13, list price $120.",
        "public", (PRICING, SUPPORT), "postgres://catalog/products/NS-100-product", "3",
        10 * _DAY,
    ),
    Record(
        "RETURNS-2", DEMO_RETAIL, "support", "Shoe return policy",
        "Customers can return unworn shoes within 30 days. Worn shoes are refunded only if "
        "they are defective.",
        "internal", (SUPPORT,), "postgres://support/policies/RETURNS-2", "2", 30 * _DAY,
    ),
    Record(
        "PROMO-88", DEMO_RETAIL, "approved-decisions", "Approved autumn promotion",
        "Approved promotion: NS-100 is 15% off until October 31. Support may quote this price.",
        "internal", (PRICING, SUPPORT), "postgres://decisions/promotions/PROMO-88", "1",
        5 * _DAY,
    ),
    Record(
        "PLAN-7", DEMO_RETAIL, "pricing", "Acquisition plan",
        "Restricted: board plan to acquire a competitor and reprice NS-100 next year.",
        "restricted", ("restricted-data",), "postgres://board/plans/PLAN-7", "1", 1 * _DAY,
    ),
    Record(
        "NS-100-other", OTHER_RETAILER, "pricing", "NS-100 discount limit",
        "NS-100 discount limit at Other Retailer: up to 50% off during clearance.",
        "internal", (PRICING,), "postgres://catalog/pricing_rules/NS-100-other", "12", 6 * _HOUR,
    ),
)  # fmt: skip

EXAMPLES: Final = (
    Example(
        "Pricing assistant asks the discount limit", "pricing-assistant",
        "What is the discount limit for NS-100?", PRICING_CORPORA,
        "The 20% rule comes back first, with its source record, version and age. The finance "
        "note and the board plan stay hidden.",
    ),
    Example(
        "Support chatbot asks the same question", "support-bot",
        "What is the discount limit for NS-100?", SUPPORT_CORPORA,
        "No internal 20% rule. It gets the approved 15% promotion, which support may quote.",
    ),
    Example(
        "Another company asks the same question", "other-company-pricing",
        "What is the discount limit for NS-100?", PRICING_CORPORA,
        "Only Other Retailer's own 50% rule. Demo Retail's records never appear.",
    ),
    Example(
        "Support chatbot asks about returns", "support-bot",
        "Can a customer return worn NS-100 shoes?", SUPPORT_CORPORA,
        "The return policy, which only support is cleared to read.",
    ),
    Example(
        "Support chatbot tries to read pricing records", "support-bot",
        "What is the discount limit for NS-100?", ("pricing",),
        "Refused with 403 POLICY_DENIED. A caller can narrow what it searches, never widen it.",
    ),
)  # fmt: skip
