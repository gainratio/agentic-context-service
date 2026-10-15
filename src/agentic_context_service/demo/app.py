"""Compose the offline demo: the real API, an in-memory store, and the OPA stand-in.

Only two things are swapped out compared to the full stack: OpenSearch becomes
`InMemorySearchStore` and the OPA server becomes `StaticPolicy` (same data tables, same rules).
The HTTP routes, the request-signature check and the policy enforcement are the production
code. The page's "Ask" button goes through a small built-in gateway that signs the request the
way your own API gateway would, then sends it to `POST /v1/context:retrieve`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from agentic_context_service.adapters.opa import PolicyDecision
from agentic_context_service.adapters.service import GovernedContextService
from agentic_context_service.api.app import create_app
from agentic_context_service.api.request_context import (
    RequestContextSigner,
    StaticTokenAuthenticator,
)
from agentic_context_service.demo.explain import explain
from agentic_context_service.demo.scenario import (
    ASSISTANTS,
    DEMO_SIGNING_KEY,
    EXAMPLES,
    GROUP_LABELS,
    JOB_LABELS,
    RECORDS,
    SENSITIVITY_LABELS,
    Assistant,
)
from agentic_context_service.testing.policy import StaticPolicy
from agentic_context_service.testing.search_store import InMemorySearchStore

RETRIEVE_PATH: Final = "/v1/context:retrieve"
_STATIC: Final = Path(__file__).with_name("static")
_MODE: Final = {
    "name": "offline",
    "title": "Offline demo",
    "summary": (
        "Runs only on your computer, with a made-up shop and made-up records. Nothing is sent "
        "anywhere, and no account or key is needed."
    ),
    "details": (
        "Offline mode. The web service, the signature check and the access rules are the real "
        "service code. Two parts are simplified so it runs without Docker: records live in "
        "memory and are matched by shared words, not by meaning, and the access rules in "
        "policies/context/data.json are applied by a built-in stand-in for Open Policy Agent. "
        "The full stack described in the README uses OpenSearch and the real Open Policy Agent."
    ),
}


class AskRequest(BaseModel):
    """What the page sends to the demo gateway."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    assistant: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=500)
    corpora: tuple[str, ...] = Field(min_length=1, max_length=10)


def create_demo_app(policy_data: Path, *, now: datetime | None = None) -> FastAPI:
    """Build the offline service with Demo Retail's records and assistants loaded."""
    moment = now or datetime.now(UTC)
    policy = StaticPolicy.from_file(policy_data)
    service = GovernedContextService(
        opa=policy,
        store=InMemorySearchStore(record.indexed(moment) for record in RECORDS),
        embedding_model="none (offline word match)",
    )
    tokens = {assistant.bearer: assistant.principal() for assistant in ASSISTANTS}
    app = create_app(
        service=service,
        signing_secret=DEMO_SIGNING_KEY,
        authenticator=StaticTokenAuthenticator(tokens),
    )
    _register_demo_routes(app, _Demo(policy, moment))
    return app


@dataclass(frozen=True, slots=True)
class _Demo:
    policy: StaticPolicy
    moment: datetime

    def documents(self) -> list[dict[str, Any]]:
        return [record.indexed(self.moment) for record in RECORDS]


def _register_demo_routes(app: FastAPI, demo: _Demo) -> None:
    @app.get("/", include_in_schema=False)
    async def home() -> RedirectResponse:
        return RedirectResponse("/demo/")

    @app.get("/demo/api/scenario", include_in_schema=False)
    async def scenario() -> dict[str, Any]:
        return _scenario(demo)

    @app.post("/demo/api/ask", include_in_schema=False)
    async def ask(body: AskRequest) -> dict[str, Any]:
        assistant = _assistant(body.assistant)
        exchange = await _ask_through_gateway(app, assistant, body)
        return {**exchange, **await _explanation(demo, assistant, body, exchange)}

    app.mount("/demo", StaticFiles(directory=_STATIC, html=True), name="demo")


def _scenario(demo: _Demo) -> dict[str, Any]:
    return {
        "mode": _MODE,
        "assistants": [_assistant_view(assistant) for assistant in ASSISTANTS],
        "records": [_record_view(document) for document in demo.documents()],
        "examples": [asdict(example) for example in EXAMPLES],
    }


def _assistant_view(assistant: Assistant) -> dict[str, Any]:
    return {
        **asdict(assistant),
        "job": JOB_LABELS[assistant.purpose],
        "groups": [GROUP_LABELS[corpus] for corpus in assistant.corpora],
    }


async def _explanation(
    demo: _Demo, assistant: Assistant, body: AskRequest, exchange: dict[str, Any]
) -> dict[str, Any]:
    response = exchange["response"]
    decision = await _decision(demo, assistant, body, response)
    outcomes = explain(demo.documents(), decision, assistant, _returned_ids(response))
    groups = decision.allowed_corpora if decision else ()
    return {
        "allowed_groups": [GROUP_LABELS.get(group, group) for group in groups],
        "outcomes": [asdict(outcome) for outcome in outcomes],
    }


async def _decision(
    demo: _Demo, assistant: Assistant, body: AskRequest, response: dict[str, Any]
) -> PolicyDecision | None:
    """The policy decision behind an answered request; None when the service refused it."""
    if response["status"] != status.HTTP_200_OK:
        return None
    return await demo.policy.authorize(_policy_question(assistant, body))


def _returned_ids(response: dict[str, Any]) -> frozenset[str]:
    results = response["body"].get("results", [])
    return frozenset(str(result["citation"]["record_id"]) for result in results)


def _policy_question(assistant: Assistant, body: AskRequest) -> dict[str, Any]:
    """The same question the service sends to the policy for this request."""
    principal = assistant.principal()
    return {
        "identity": {
            "subject": principal.subject,
            "tenant_id": principal.tenant_id,
            "teams": list(principal.teams),
            "entitlements": list(principal.entitlements),
        },
        "workload": {
            "team_id": assistant.team,
            "app_id": assistant.id,
            "workflow_id": assistant.workflow,
            "workflow_revision": "v1",
            "agent_id": assistant.id,
            "environment": "development",
            "cost_center": "retail",
            "headers_verified": True,
        },
        "request": {
            "operation": "retrieve",
            "purpose": assistant.purpose,
            "corpora": list(body.corpora),
            "classifications": [],
            "namespace": None,
            "source": None,
        },
    }


def _record_view(document: dict[str, Any]) -> dict[str, Any]:
    governance = document["governance"]
    return {
        "record_id": document["document_id"],
        "tenant_id": document["tenant_id"],
        "corpus": document["domain"],
        "group": GROUP_LABELS[document["domain"]],
        "title": document["title"],
        "text": document["content"],
        "classification": governance["classification"],
        "sensitivity": SENSITIVITY_LABELS[governance["classification"]],
        "purposes": governance["allowed_purposes"],
        "readers": [JOB_LABELS[purpose] for purpose in governance["allowed_purposes"]],
        "uri": document["source"]["uri"],
        "version": document["source"]["version"],
        "updated_at": document["validity"]["source_updated_at"],
    }


def _assistant(assistant_id: str) -> Assistant:
    for assistant in ASSISTANTS:
        if assistant.id == assistant_id:
            return assistant
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown assistant")


async def _ask_through_gateway(
    app: FastAPI, assistant: Assistant, body: AskRequest
) -> dict[str, Any]:
    headers = signed_headers(assistant)
    payload = retrieve_body(assistant, body.question, body.corpora)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://acs.local") as client:
        response = await client.post(RETRIEVE_PATH, headers=headers, json=payload)
    return {
        "request": {"method": "POST", "path": RETRIEVE_PATH, "headers": headers, "body": payload},
        "response": {"status": response.status_code, "body": response.json()},
    }


def signed_headers(assistant: Assistant) -> dict[str, str]:
    """The identity headers a trusted gateway attaches, plus their HMAC signature."""
    headers = {
        "Authorization": f"Bearer {assistant.bearer}",
        "X-Team-ID": assistant.team,
        "X-App-ID": assistant.id,
        "X-Workflow-ID": assistant.workflow,
        "X-Workflow-Revision": "v1",
        "X-Agent-ID": assistant.id,
        "X-Environment": "development",
        "X-Cost-Center": "retail",
        "X-Request-ID": f"req-{uuid.uuid4().hex[:12]}",
        "X-Trace-ID": uuid.uuid4().hex,
        "X-ACS-Timestamp": str(int(time.time())),
    }
    headers["X-ACS-Signature"] = RequestContextSigner(DEMO_SIGNING_KEY).sign(headers)
    return headers


def retrieve_body(assistant: Assistant, question: str, corpora: tuple[str, ...]) -> dict[str, Any]:
    """The JSON body of one retrieval request."""
    return {
        "query": question,
        "purpose": assistant.purpose,
        "corpora": list(corpora),
        "filters": {},
        "retrieval": {
            "mode": "lexical",
            "candidate_limit": 20,
            "result_limit": 3,
            "max_context_tokens": 2000,
        },
    }
