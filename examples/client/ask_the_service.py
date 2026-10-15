"""Ask the service for context the way your AI assistant would.

Start the service with `make demo`, then in a second terminal run:
    uv run python examples/client/ask_the_service.py
"""

import asyncio
import time
import uuid

import httpx

from agentic_context_service.api.request_context import RequestContextSigner

SERVICE_URL = "http://127.0.0.1:8090"
# The demo's signing key. In production your API gateway holds the key and signs for you.
SIGNING_KEY = b"offline-demo-signing-key-not-for-production"


def signed_headers() -> dict[str, str]:
    headers = {
        "Authorization": "Bearer pricing-assistant-token",  # who is asking
        "X-Team-ID": "pricing",
        "X-App-ID": "pricing-assistant",
        "X-Workflow-ID": "price-check",
        "X-Workflow-Revision": "v1",
        "X-Agent-ID": "pricing-assistant",
        "X-Environment": "development",
        "X-Cost-Center": "retail",
        "X-Request-ID": str(uuid.uuid4()),
        "X-Trace-ID": uuid.uuid4().hex,
        "X-ACS-Timestamp": str(int(time.time())),
    }
    headers["X-ACS-Signature"] = RequestContextSigner(SIGNING_KEY).sign(headers)
    return headers


async def ask(client: httpx.AsyncClient, question: str) -> list[dict]:
    response = await client.post(
        "/v1/context:retrieve",
        headers=signed_headers(),
        json={
            "query": question,
            "purpose": "pricing-analysis",  # the job this answer is for
            "corpora": ["pricing", "product", "approved-decisions"],
            "filters": {},
            "retrieval": {
                "mode": "lexical",
                "candidate_limit": 20,
                "result_limit": 3,
                "max_context_tokens": 2000,
            },
        },
    )
    response.raise_for_status()
    return response.json()["results"]


async def main(client: httpx.AsyncClient) -> None:
    for result in await ask(client, "What is the discount limit for NS-100?"):
        citation = result["citation"]
        print(result["text"])
        print(f"  from {citation['source_uri']} version {citation['source_version']}")


async def run() -> None:
    async with httpx.AsyncClient(base_url=SERVICE_URL) as client:
        await main(client)


if __name__ == "__main__":
    asyncio.run(run())
