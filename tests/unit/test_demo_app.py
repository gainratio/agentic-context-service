"""The offline browser demo answers through the real API, signature checks, and policy."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from agentic_context_service.demo.app import create_demo_app

POLICY_DATA = Path(__file__).parents[2] / "policies/context/data.json"
QUESTION = "What is the discount limit for NS-100?"
PRICING = ["pricing", "product", "approved-decisions"]
SUPPORT = ["product", "support", "approved-decisions"]


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_demo_app(POLICY_DATA))
    async with httpx.AsyncClient(transport=transport, base_url="http://demo") as test_client:
        yield test_client


async def _ask(
    client: httpx.AsyncClient, assistant: str, corpora: list[str], question: str = QUESTION
) -> dict[str, object]:
    response = await client.post(
        "/demo/api/ask",
        json={"assistant": assistant, "question": question, "corpora": corpora},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def _record_ids(payload: dict[str, object]) -> list[str]:
    response = payload["response"]
    assert isinstance(response, dict)
    return [result["citation"]["record_id"] for result in response["body"]["results"]]


@pytest.mark.asyncio
async def test_should_serve_the_page_when_a_browser_opens_the_root(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    page = await client.get("/", follow_redirects=True)

    # Then
    assert page.status_code == 200
    assert "Offline demo" in page.text
    assert '<script src="app.js"' in page.text


@pytest.mark.asyncio
async def test_should_describe_the_scenario_when_the_page_loads(client: httpx.AsyncClient) -> None:
    # Given / When
    scenario = (await client.get("/demo/api/scenario")).json()

    # Then
    assert {a["id"] for a in scenario["assistants"]} == {
        "pricing-assistant",
        "support-bot",
        "other-company-pricing",
    }
    assert len(scenario["records"]) == 7
    assert scenario["mode"]["name"] == "offline"
    assert scenario["examples"][0]["question"] == QUESTION


@pytest.mark.asyncio
async def test_should_return_the_cited_pricing_rule_when_the_pricing_assistant_asks(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    payload = await _ask(client, "pricing-assistant", PRICING)

    # Then
    assert _record_ids(payload)[0] == "NS-100"
    first = payload["response"]["body"]["results"][0]  # type: ignore[index]
    assert first["citation"]["source_uri"] == "postgres://catalog/pricing_rules/NS-100"
    assert first["citation"]["source_version"] == "7"
    assert first["freshness"]["age_seconds"] >= 7200
    assert "NS-100-margin" not in _record_ids(payload)


@pytest.mark.asyncio
async def test_should_show_the_signed_request_when_any_assistant_asks(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    payload = await _ask(client, "pricing-assistant", PRICING)

    # Then
    request = payload["request"]
    assert request["method"] == "POST"  # type: ignore[index]
    assert request["path"] == "/v1/context:retrieve"  # type: ignore[index]
    assert len(request["headers"]["X-ACS-Signature"]) == 64  # type: ignore[index]
    assert request["body"]["purpose"] == "pricing-analysis"  # type: ignore[index]


@pytest.mark.asyncio
async def test_should_withhold_the_internal_limit_when_the_support_bot_asks(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    payload = await _ask(client, "support-bot", SUPPORT)

    # Then
    assert "NS-100" not in _record_ids(payload)
    assert "PROMO-88" in _record_ids(payload)


@pytest.mark.asyncio
async def test_should_return_only_its_own_record_when_another_company_asks(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    payload = await _ask(client, "other-company-pricing", PRICING)

    # Then
    assert _record_ids(payload) == ["NS-100-other"]


@pytest.mark.asyncio
async def test_should_refuse_when_the_support_bot_asks_for_pricing_records(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    payload = await _ask(client, "support-bot", ["pricing"])

    # Then
    assert payload["response"] == {  # the real API's refusal, passed through unchanged
        "status": 403,
        "body": {
            "code": "POLICY_DENIED",
            "message": "forbidden",
            "request_id": payload["request"]["headers"]["X-Request-ID"],  # type: ignore[index]
            "retryable": False,
        },
    }


@pytest.mark.asyncio
async def test_should_reject_the_question_when_the_assistant_is_unknown(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    response = await client.post(
        "/demo/api/ask",
        json={"assistant": "intruder", "question": QUESTION, "corpora": PRICING},
    )

    # Then
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_should_reject_unsigned_calls_when_they_skip_the_gateway(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    response = await client.post("/v1/context:retrieve", json={})

    # Then
    assert response.status_code in {400, 401}


@pytest.mark.asyncio
async def test_should_explain_every_record_when_the_pricing_assistant_asks(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    payload = await _ask(client, "pricing-assistant", PRICING)

    # Then
    outcomes = {o["record_id"]: o["status"] for o in payload["outcomes"]}  # type: ignore[attr-defined]
    assert outcomes["NS-100"] == "returned"
    assert outcomes["NS-100-margin"] == "set_aside"
    assert outcomes["NS-100-other"] == "set_aside"
    assert payload["allowed_groups"] == ["pricing rules", "product facts", "approved decisions"]


@pytest.mark.asyncio
async def test_should_mark_nothing_searched_when_the_request_is_refused(
    client: httpx.AsyncClient,
) -> None:
    # Given / When
    payload = await _ask(client, "support-bot", ["pricing"])

    # Then
    statuses = {o["status"] for o in payload["outcomes"]}  # type: ignore[attr-defined]
    assert statuses == {"not_searched"}
    assert payload["allowed_groups"] == []
