# Agentic Context Service

A lookup service for your company's AI assistants: each one gets only the facts it may see, with the source of each.

**Try it after cloning: `make demo`** opens it in your browser. No API key, no Docker.

[![CI](https://github.com/gainratio/agentic-context-service/actions/workflows/dagger.yml/badge.svg)](https://github.com/gainratio/agentic-context-service/actions/workflows/dagger.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Companies that run several AI assistants (programs that answer questions or propose actions
using a language model) usually connect each one to the company's databases on its own. Each
connection re-implements who may see what. When an assistant quotes a price or a policy, nobody
can tell which record it came from or how old it was.

Agentic Context Service is one HTTP service your assistants ask instead. Your databases send it
each change once. When an assistant asks a question, the service first removes everything that
assistant is not allowed to see, then searches what is left, and returns short passages. Each
passage names its source record, version, and age. You run it on your own machines.

**Technical docs:** [Architecture](docs/ARCHITECTURE.md) · [Getting started for developers](docs/GETTING_STARTED.md) · [API contract](packages/contracts/openapi.yaml) · [Threat model](docs/threat-model/README.md)

![The demo page after the pricing assistant asks "What is the discount limit for NS-100?": four plain steps show the question, what the service did (checked the signature, blocked 4 of 7 records), the 3 facts sent back with their sources, and why it matters](docs/assets/demo.png)

## Try it

You need `git`, `make`, and [uv](https://docs.astral.sh/uv/). uv installs Python 3.13 for you
if needed.

```bash
git clone https://github.com/gainratio/agentic-context-service.git
cd agentic-context-service
make demo
```

The first run downloads Python and the packages, which takes a minute or two. Then your browser
opens http://127.0.0.1:8090/demo/. Press Ctrl+C in the terminal to stop it.

The page tells a short story. Demo Retail is a made-up shoe shop with two AI assistants: one
helps its pricing team, one answers customers at the help desk. A second shop, Other Retailer,
uses the same service. Between them the service holds seven records: pricing rules, a product
fact, a return policy, an approved sale, a finance note, and a board plan. Pick a scenario:

1. **The pricing assistant asks for a discount limit.** The 20% rule comes back first, with where
   it came from: record `NS-100` in the catalog database, version 7, two hours old. The finance
   note and the board plan are set aside.
2. **The customer help assistant asks the same discount question.** It does not get the internal 20% rule. It
   gets the approved 15% sale, which the help desk may quote.
3. **Another shop's assistant asks the same discount question.** It gets only its own shop's rule.
4. **The customer help assistant asks about returns.** It gets the return policy, which only the
   help desk may read.
5. **The customer help assistant tries to open pricing rules.** Refused with `403
   POLICY_DENIED`. Asking for more than its job allows never gets it more.

For each one the page shows, in plain words, the question, what the service did, what the
assistant got back, why it matters, and what happened to each of the seven records. A
"For developers" panel shows the exact HTTP request and response and lets you ask your own
question.

The page says which mode it runs in. `make demo` is the **offline demo**: the HTTP API, the
signature check, and the access rules are the real service code, but records live in memory and
are matched by words, and the access rules from
[`policies/context/data.json`](policies/context/data.json) are applied by a small built-in
stand-in for Open Policy Agent. CI checks that the stand-in gives the same answers as the real
Open Policy Agent. Nothing leaves your computer. The full stack below swaps in
OpenSearch, live database changes, and the real Open Policy Agent.

Prefer the terminal? This prints a smaller version of the same check, run in-process with no
browser and no server:

```bash
uv run python examples/quickstart/governed_retrieval.py
```

```text
published 3 records: a pricing rule, a finance-only note, another company's rule
pricing-analysis asks "What is the discount limit for NS-100?" -> 1 result(s)
  NS-100 may be discounted at most 20% without pricing-lead approval.
  source: postgres://catalog/NS-100 v7, 90s old, trust: verified
customer-support asks "What is the discount limit for NS-100?" -> 0 result(s)
```

## Use it in your own code

Your assistant calls the service over HTTP: one `POST /v1/context:retrieve` per question. Any
language works (the signature recipe is below). In Python you need an HTTP client and, for local
testing, this package's request signer. The package is the whole server, about 50 dependencies,
so in production you may prefer to compute the signature yourself:

```bash
pip install httpx "agentic-context-service @ git+https://github.com/gainratio/agentic-context-service"
```

With `make demo` running, this is a complete pricing-assistant client
([`examples/client/ask_the_service.py`](examples/client/ask_the_service.py)):

```python
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
```

It prints:

```text
NS-100 discount limit: at most 20% off list price without pricing-lead approval.
  from postgres://catalog/pricing_rules/NS-100 version 7
NS-100 is a waterproof trail running shoe, sizes 6 to 13, list price $120.
  from postgres://catalog/products/NS-100-product version 3
Approved promotion: NS-100 is 15% off until October 31. Support may quote this price.
  from postgres://decisions/promotions/PROMO-88 version 1
```

What to know when you wire it into a real assistant:

- **The headers say who is asking and for which job.** The bearer token identifies the
  assistant. The service decides what it may see from the token and the `purpose`, never from
  anything else the caller claims.
- **The signature normally comes from your API gateway.** In production your gateway holds the
  key, so assistants never see it. The demo key above is only for the demo. In any language:
  take these 11 headers in this order, `authorization`, `x-team-id`, `x-app-id`,
  `x-workflow-id`, `x-workflow-revision`, `x-agent-id`, `x-environment`, `x-cost-center`,
  `x-request-id`, `x-trace-id`, `x-acs-timestamp`; write each as `name:value` (lowercase name,
  trimmed value); join them with `\n`; and send the hex HMAC-SHA256 of that text as
  `X-ACS-Signature`. The timestamp is Unix seconds. The service refuses a signature older than
  five minutes or more than 30 seconds in the future. The shared key must be at least 32 bytes.
- **Each result carries its evidence.** `citation` names the source system, record, and version;
  `freshness` gives its age; `trust_class` says how much to trust it. Put these in the
  assistant's prompt so its answer can cite them.
- **Refusals are explicit.** Every error body is
  `{"code": ..., "message": ..., "request_id": ..., "retryable": ...}`. `400 INVALID_REQUEST`
  means the body did not match the contract, `401 UNAUTHENTICATED` means the identity or
  signature failed, `403 POLICY_DENIED` means the assistant asked for something its job does not
  allow, and `409 CONTEXT_STALE` means you set `stale_behavior: "fail"` and a match was older
  than your `max_age_seconds`.

The [API contract](packages/contracts/openapi.yaml) lists every route and field, and the
[architecture guide](docs/ARCHITECTURE.md#api-shape) explains them. The service can also store
and search assistant memory (`/v1/memories`). A test runs this exact file against the service,
so the code and output above cannot drift.

## How it works

Changes in PostgreSQL are picked up from the database's change log (Debezium) and passed through
a queue (Redpanda) to an indexer. The indexer splits each record into chunks and stores them in
OpenSearch with the record's version, so a late or replayed change never overwrites a newer one
and a deleted record stays deleted. An assistant sends one signed request that says which company
it works for and what job it is doing. A policy engine (Open Policy Agent) turns that into
filters that are applied before any ranking, and a caller's own filters can narrow them but never
widen them. OpenSearch then ranks what is left by exact words and by meaning, and the service
returns the top passages with their sources and ages.

## What it does not do

- **It is Beta.** Version 0.1.0 has no tagged release and is not published to PyPI. You install
  it from this repository.
- **It is not a chat app or a framework for building assistants.** It is the lookup your
  assistant calls.
- **It knows one assistant out of the box.** The stock entry point (`bootstrap.py`) accepts a
  single token, `ACS_DEMO_TOKEN`, and has no setting for more. To give each of your assistants
  its own identity, implement `BearerAuthenticator` from
  [`api/request_context.py`](src/agentic_context_service/api/request_context.py) (for example,
  one that validates your identity provider's tokens) and pass it to
  `create_app(authenticator=...)` from your own entry point.
- **It is not the source of truth.** Your databases are. The index is updated a moment after the
  database changes, not in the same transaction.
- **The local stack is for trying it, not for production.** It turns off TLS, private
  networking, and OpenSearch's per-document security so it runs on a laptop. There is no high
  availability, backup and restore, or load testing yet. See the [roadmap](ROADMAP.md).
- **The offline demo and the terminal quickstart match words only.** Search by meaning needs
  the full stack below. The offline demo also cannot store assistant memory.
- **It cannot protect you from a compromised server or operator**, or from what an AI provider
  does with data you choose to send it. Nothing leaves your machines unless you turn on the
  optional live AI mode (`ACS_SHOWCASE_AGENT_MODE=deep`) in the full-stack dashboard.

## When to use something else

| If you have | Use |
| --- | --- |
| One assistant and one data source | Let the assistant query that source directly |
| Documents only, and no per-user or per-team access rules | A vector database with a retrieval library |
| A need for a managed service, and you accept its data handling | A hosted enterprise search product |
| Several assistants, access rules, and a need to trace every answer to a record | Agentic Context Service |

## Run the full local stack

This runs PostgreSQL, Debezium, Redpanda, OpenSearch, OPA, the API, and the indexer in Docker.
You need Docker with Compose v2, at least 4 GiB of memory for Docker, and `make`. `make up`
checks Docker's memory first and stops with a clear message if it is too small; set
`ACS_SKIP_MEMORY_CHECK=1` to try anyway. Every image is published for amd64 and arm64, so Apple
silicon runs it without emulation.

```bash
cp .env.example .env
make bootstrap
make up
make seed
make stack-demo
```

`make stack-demo` walks through a pricing question with citations, a database update showing up
in search, an assistant being refused, and saved assistant memory. It exits with an error if any
step does not behave as expected. While the stack runs, a live dashboard is at
http://localhost:8080/showcase/. Stop it with `make down`. Details are in
[operations](docs/operations.md).

## Develop

```bash
make bootstrap
make verify
```

`make verify` runs the same checks as CI: lint, strict type checks, tests with at least 90%
coverage, security scans, and a retrieval-quality evaluation. It takes about 20 seconds. The tests
ignore any `.env` file, so it is safe to run after the quickstart above. `make ui` runs the
browser tests for the demo page and the dashboard.
[Getting started for developers](docs/GETTING_STARTED.md) covers prerequisites, a map of the
code, and a walkthrough of a first change.

## More detail

- [Architecture](docs/ARCHITECTURE.md): the data path, API shape, security model, configuration,
  and what the tests prove.
- [Getting started for developers](docs/GETTING_STARTED.md): from clone to a green build and your
  first change.
- [Five-minute architecture](docs/architecture/README.md): the design rules on one page.
- [Interactive architecture map](docs/architecture/index.html): a guided visual tour.
- [Specification](docs/specification.md): the full engineering contract and acceptance criteria.
- [Operations](docs/operations.md): health checks and what to do when something breaks.
- [Threat model](docs/threat-model/README.md): what is protected and what is not.
- [Design decisions](docs/adr/): one short record per decision.
- [API contract](packages/contracts/openapi.yaml): the OpenAPI definition.
- [Examples](examples/): the client above, the terminal quickstart, and two AI agent examples
  where code, not the model, approves the action.
- [Demo source](src/agentic_context_service/demo/): the offline demo's records, assistants, and
  page.
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [CHANGELOG.md](CHANGELOG.md),
  and [ROADMAP.md](ROADMAP.md).

## License

MIT. See [LICENSE](LICENSE).
