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
    why: str


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
        "support-bot", "Customer help assistant", "Demo Retail", DEMO_RETAIL,
        "support-bot-token", "support", "customer-chat", SUPPORT, SUPPORT_CORPORA,
    ),
    Assistant(
        "other-company-pricing", "Pricing assistant", "Other Retailer",
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
        "NS-100-other", OTHER_RETAILER, "pricing", "NS-100 clearance discount limit",
        "NS-100 discount limit at Other Retailer: up to 50% off during clearance.",
        "internal", (PRICING,), "postgres://catalog/pricing_rules/NS-100-other", "12", 6 * _HOUR,
    ),
)  # fmt: skip

EXAMPLES: Final = (
    Example(
        "The pricing assistant asks for a discount limit", "pricing-assistant",
        "What is the discount limit for NS-100?", PRICING_CORPORA,
        "Without a check like this, a pricing assistant wired straight into the databases could "
        "also read the finance team's margin note and the board's plan. Here it gets only what "
        "the pricing team may use, and each fact says where it came from.",
    ),
    Example(
        "The customer help assistant asks the same discount question", "support-bot",
        "What is the discount limit for NS-100?", SUPPORT_CORPORA,
        "The help desk can tell a customer about the 15% sale, but it never sees the internal 20% "
        "limit that customers must not hear about.",
    ),
    Example(
        "Another shop's assistant asks the same discount question", "other-company-pricing",
        "What is the discount limit for NS-100?", PRICING_CORPORA,
        "Two shops share one service, and neither can ever see the other's prices.",
    ),
    Example(
        "The customer help assistant asks about returns", "support-bot",
        "Can a customer return worn NS-100 shoes?", SUPPORT_CORPORA,
        "Only the help desk is cleared to read the return policy, and it gets it with its source "
        "and age.",
    ),
    Example(
        "The customer help assistant tries to open pricing rules", "support-bot",
        "What is the discount limit for NS-100?", ("pricing",),
        "Asking for more than its job allows does not get it more. The service refuses outright "
        "instead of handing over a partial answer.",
    ),
)  # fmt: skip

# Plain-language names the page shows instead of internal identifiers.
JOB_LABELS: Final = {
    PRICING: "the pricing team",
    SUPPORT: "the help desk",
    "finance-review": "the finance team",
    "restricted-data": "the board",
}
GROUP_LABELS: Final = {
    "pricing": "pricing rules",
    "product": "product facts",
    "support": "help-desk policies",
    "approved-decisions": "approved decisions",
}
SENSITIVITY_LABELS: Final = {
    "public": "public",
    "internal": "staff only",
    "confidential": "confidential",
    "restricted": "restricted",
}
