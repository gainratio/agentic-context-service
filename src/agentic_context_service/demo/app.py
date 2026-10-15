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
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from agentic_context_service.adapters.service import GovernedContextService
from agentic_context_service.api.app import create_app
from agentic_context_service.api.request_context import (
    RequestContextSigner,
    StaticTokenAuthenticator,
)
from agentic_context_service.demo.scenario import (
    ASSISTANTS,
    DEMO_SIGNING_KEY,
    EXAMPLES,
    RECORDS,
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
        "Everything runs on this computer. No API key, no network, no Docker. Records live in "
        "memory and are matched by words, not meaning. Access rules come from "
        "policies/context/data.json, applied by a built-in stand-in for Open Policy Agent. "
        "The HTTP API, signature check and policy enforcement are the real service code."
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
    service = GovernedContextService(
        opa=StaticPolicy.from_file(policy_data),
        store=InMemorySearchStore(record.indexed(moment) for record in RECORDS),
        embedding_model="none (offline word match)",
    )
    tokens = {assistant.bearer: assistant.principal() for assistant in ASSISTANTS}
    app = create_app(
        service=service,
        signing_secret=DEMO_SIGNING_KEY,
        authenticator=StaticTokenAuthenticator(tokens),
    )
    _register_demo_routes(app, moment)
    return app


def _register_demo_routes(app: FastAPI, moment: datetime) -> None:
    @app.get("/", include_in_schema=False)
    async def home() -> RedirectResponse:
        return RedirectResponse("/demo/")

    @app.get("/demo/api/scenario", include_in_schema=False)
    async def scenario() -> dict[str, Any]:
        return _scenario(moment)

    @app.post("/demo/api/ask", include_in_schema=False)
    async def ask(body: AskRequest) -> dict[str, Any]:
        return await _ask_through_gateway(app, _assistant(body.assistant), body)

    app.mount("/demo", StaticFiles(directory=_STATIC, html=True), name="demo")


def _scenario(moment: datetime) -> dict[str, Any]:
    return {
        "mode": _MODE,
        "assistants": [asdict(assistant) for assistant in ASSISTANTS],
        "records": [_record_view(record.indexed(moment)) for record in RECORDS],
        "examples": [asdict(example) for example in EXAMPLES],
    }


def _record_view(document: dict[str, Any]) -> dict[str, Any]:
    governance = document["governance"]
    return {
        "record_id": document["document_id"],
        "tenant_id": document["tenant_id"],
        "corpus": document["domain"],
        "title": document["title"],
        "text": document["content"],
        "classification": governance["classification"],
        "purposes": governance["allowed_purposes"],
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
