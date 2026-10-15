"""StaticPolicy (the offline stand-in) must give the same answer as the real OPA server.

Runs only when ACS_OPA_PARITY_URL points at an OPA server loaded with policies/; CI's Dagger
gate starts one (openpolicyagent/opa, same pinned image as the Compose stack) and sets it.
"""

from __future__ import annotations

import asyncio
import itertools
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from agentic_context_service.adapters.opa import OPAClient, PolicyDecision
from agentic_context_service.testing.policy import StaticPolicy

ROOT = Path(__file__).parents[2]
OPA_URL = os.environ.get("ACS_OPA_PARITY_URL", "")
BATCH = 50

PURPOSES = ("pricing-analysis", "customer-support", "memory-management", "restricted-data", "nope")
ENTITLEMENTS = (
    ("pricing-analysis",),
    ("customer-support", "restricted-data"),
    ("restricted-data",),
    (),
)
CORPORA = ((), ("pricing",), ("pricing", "support"), ("memory",))
CLASSES = ((), ("restricted",), ("internal", "public"))
OPERATIONS = ("retrieve", "freshness.read", "memory.write")
SOURCES = (None, "postgresql")
ENVIRONMENTS = ("development", "production")
VERIFIED = (True, False)
NAMESPACES = (None, "t1:development:wf:v1:s1:sess:_")


@dataclass(frozen=True, slots=True)
class Case:
    purpose: str
    entitlements: tuple[str, ...]
    corpora: tuple[str, ...]
    classifications: tuple[str, ...]
    operation: str
    source: str | None
    environment: str
    verified: bool
    namespace: str | None

    def policy_input(self) -> dict[str, object]:
        return {
            "identity": {
                "subject": "s1",
                "tenant_id": "t1",
                "teams": ["x"],
                "entitlements": list(self.entitlements),
            },
            "workload": {
                "team_id": "x",
                "app_id": "a",
                "workflow_id": "wf",
                "workflow_revision": "v1",
                "agent_id": "ag",
                "environment": self.environment,
                "cost_center": "c",
                "headers_verified": self.verified,
            },
            "request": {
                "operation": self.operation,
                "purpose": self.purpose,
                "corpora": list(self.corpora),
                "classifications": list(self.classifications),
                "namespace": self.namespace,
                "source": self.source,
            },
        }


def _cases() -> list[Case]:
    grid = itertools.product(
        PURPOSES,
        ENTITLEMENTS,
        CORPORA,
        CLASSES,
        OPERATIONS,
        SOURCES,
        ENVIRONMENTS,
        VERIFIED,
        NAMESPACES,
    )
    return [Case(*values) for values in grid]


async def _answer(policy: StaticPolicy | OPAClient, case: Case) -> PolicyDecision | str:
    try:
        return await policy.authorize(case.policy_input())
    except Exception as error:  # the error type is the answer being compared
        return type(error).__name__


async def _disagreements(cases: list[Case]) -> list[Case]:
    static = StaticPolicy.from_file(ROOT / "policies/context/data.json")
    found: list[Case] = []
    async with httpx.AsyncClient() as client:
        opa = OPAClient(OPA_URL, client=client, timeout=10.0)
        for start in range(0, len(cases), BATCH):
            batch = cases[start : start + BATCH]
            mine = await asyncio.gather(*(_answer(static, case) for case in batch))
            theirs = await asyncio.gather(*(_answer(opa, case) for case in batch))
            found.extend(case for case, a, b in zip(batch, mine, theirs, strict=True) if a != b)
    return found


@pytest.mark.integration
@pytest.mark.skipif(not OPA_URL, reason="needs ACS_OPA_PARITY_URL (set by the Dagger gate)")
def test_should_match_real_opa_when_given_the_same_inputs() -> None:
    # Given
    cases = _cases()

    # When
    disagreements = asyncio.run(_disagreements(cases))

    # Then
    assert len(cases) == 11520
    assert disagreements == [], f"{len(disagreements)} disagree, first: {disagreements[:3]}"
