# Getting started for developers

This takes you from a fresh clone to the browser demo, a green local build, and your first
change. Every command here was run on macOS (Apple silicon) from a fresh clone of the branch on
2026-10-15. Times are from that run, with uv and Playwright caches already warm; a first run on a
new machine downloads Python 3.13, the packages, and Chromium, which takes a few minutes.

## 1. Prerequisites

| Tool | Version | How to get it |
| --- | --- | --- |
| `git` and `make` | any | Preinstalled on macOS and most Linux systems. Every `make` target is a thin wrapper around `uv run poe <task>`. |
| [uv](https://docs.astral.sh/uv/) | 0.8 or later | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python | 3.13 exactly (`>=3.13,<3.14`) | You do not need to install it. `uv` downloads 3.13 on first sync if your system Python is different. |
| Node.js + npm | Node 22 or later | Only for the browser tests (`make ui`). |
| Docker with Compose v2 | recent, with at least 4 GiB of memory | Only for the full local stack (`make up`). Redpanda reserves 768 MiB and OpenSearch about 1 GiB; give Docker Desktop 4 GiB under Settings > Resources. `make up` refuses a smaller Docker VM; `ACS_SKIP_MEMORY_CHECK=1 make up` skips that check. |
| [Dagger](https://docs.dagger.io/) | 0.21.8 | Optional. Only to run the exact CI container locally. |

Local traps we actually hit:

- **Plain `uv sync` is not enough for the full check.** It skips the optional `agent` extra, and
  one unit test then fails with `ModuleNotFoundError: No module named 'pydantic_ai'`. Use
  `make bootstrap` (which runs `uv sync --all-extras --all-groups`).
- **Ports.** `make demo` uses 8090, and `make ui` starts its own servers on 8081 and 8091. The
  Docker stack binds 8080, 5432, 9200, 19092 and others, and its Compose project is always named
  `agentic-context-service`, so only one checkout's stack can run at a time. Stop another one with
  `make down` in that checkout.
- **Run `make` from the repository root.** The demo reads the policy tables from
  `policies/context/data.json` relative to where you start it.

## 2. Clone, install, and see it work

```bash
git clone https://github.com/gainratio/agentic-context-service.git
cd agentic-context-service
make bootstrap
make demo
```

`make bootstrap` took under a second with a warm cache. `make demo` was serving 3 seconds later
and opened http://127.0.0.1:8090/demo/ in the default browser. The terminal shows:

```text
Demo running at http://127.0.0.1:8090/demo/ (press Ctrl+C to stop)
```

Click the example buttons on the page. The [README](../README.md#try-it) explains what each one
shows. With the demo still running, call the API from a second terminal the way an assistant
would:

```bash
uv run python examples/client/ask_the_service.py
```

It prints three cited passages, starting with
`NS-100 discount limit: at most 20% off list price without pricing-lead approval.`
Stop the demo with Ctrl+C.

There is also a terminal-only check that needs no server:

```bash
uv run python examples/quickstart/governed_retrieval.py
```

## 3. The full check (the same thing CI runs)

```bash
make verify
```

CI runs this same task (`uv run poe verify`) inside a Dagger container. It runs, in order:
formatting and lint (Ruff), strict type checks (mypy), a complexity limit (xenon, grade A),
unit and contract tests with at least 90% line and branch coverage, integration tests (one of
them starts the demo command on a real port), BDD scenarios, security scans (Bandit and
pip-audit), and the offline retrieval evaluation.

It took 18 seconds. The test lines in a passing run look like this:

```text
====================== 311 passed, 4 deselected in 4.72s =======================
================= 1 passed, 1 skipped, 55 deselected in 0.95s ==================
============================== 2 passed in 0.65s ===============================
Evaluation PASS: 3 queries -> .../reports/evaluation.json
```

The browser tests are a separate check (CI runs them as their own workflow). They drive the demo
page and the full-stack dashboard in Chromium; the demo tests also fail on any browser console
error:

```bash
make ui-install   # once: npm ci + Playwright's Chromium
make ui
```

`make ui-install` took 1 second with Chromium already downloaded, and `make ui` took 3 seconds,
ending in `3 passed`.

## 4. Map of the code

| Path | What it is |
| --- | --- |
| `src/agentic_context_service/domain/models.py` | The core data types: documents, change events, queries, results, citations. No vendor imports. |
| `src/agentic_context_service/application/` | The behavior: `retrieval.py` (permission filtering, hybrid ranking, freshness), `ingestion.py` (applying change events), `memory.py` (assistant memory). |
| `src/agentic_context_service/ports/` | Small `Protocol` interfaces the application depends on. |
| `src/agentic_context_service/adapters/` | Real implementations: OpenSearch, OPA, embeddings, telemetry, and `service.py`, which applies the policy decision before every storage call. |
| `src/agentic_context_service/api/` | The FastAPI routes (`app.py`), request signing (`request_context.py`), and the full-stack dashboard. |
| `src/agentic_context_service/demo/` | The offline browser demo: `scenario.py` (the made-up company, its records and assistants), `app.py` (wiring plus the small signing gateway the page calls), `cli.py` (`make demo`), and `static/` (the page). |
| `src/agentic_context_service/testing/` | Offline stand-ins used by tests, the demo, and the quickstart: `search_store.py` (for OpenSearch), `policy.py` (for OPA), and the in-memory store and fixed clock. |
| `src/agentic_context_service/bootstrap.py`, `indexer.py` | Where the API and the indexer are wired together from real adapters. |
| `policies/` | The OPA policy (`authz.rego`) and its data tables (`data.json`) that decide what each caller may see. |
| `examples/` | `client/` (the README's client), `quickstart/` (terminal check), and two AI agent examples. |
| `deploy/compose/`, `connectors/` | The local Docker stack and the Debezium/OpenSearch configuration. |
| `tests/` | `unit/`, `integration/`, `contract/`, `security/`, `repository/` (README and repo rules), `bdd/` (with `features/`), and `e2e/` (Playwright). |

## 5. Make your first change

A typical small change is a retrieval rule. Today a record whose age is exactly the caller's
`max_age_seconds` still counts as fresh (`age > max_age_seconds` drops it only after that).
Say you want the limit to be exclusive instead.

1. Create a branch: `git checkout -b fix/exclusive-freshness-limit`.
2. Write the failing test first, in `tests/unit/test_retrieval.py`. The file has a `doc(...)`
   helper that builds a document of a given `age_seconds`, a `seed(...)` helper that stores it, and
   a `query(...)` helper that builds the question.
   Follow `test_retriever_enforces_tenant_corpus_purpose_filters_and_freshness`: seed a document
   with `age_seconds=300`, query with `max_age_seconds=300`, and expect no result.
3. Run just that file and watch the new test fail:

   ```bash
   uv run pytest tests/unit/test_retrieval.py -q
   ```

   It runs 6 tests in under a second before you add yours.
4. Change the rule in `src/agentic_context_service/application/retrieval.py`. Freshness is
   decided in `_too_old`, and the other visibility rules are in `_eligible` just above it.
5. Run the file again until it passes, then run `make verify` before you push.

If the change touches the API contract, also update
[`packages/contracts/openapi.yaml`](../packages/contracts/openapi.yaml). If it changes a
significant design decision, add an ADR under [`docs/adr/`](adr/). If it changes what the demo
page shows, update `tests/e2e/demo.spec.mjs` and run `make ui`.

## 6. Open a pull request

- **Branch names** follow the commit type: `feat/...`, `fix/...`, `docs/...`, `ci/...`,
  `chore/...`. Commit messages use the same prefixes (`fix: require deep agent tool calls ...`).
- **CI checks** on every pull request: `Dagger` (it checks the exact commit, runs
  `python -m scripts.validate_contracts`, then `make verify` in a container), `Chromium showcase
  proof` (the `make ui` browser tests), `Security evidence` (an SBOM and Bandit), and
  `GitGuardian Security Checks` (secret scanning).
- **Reviewers look for** a test that failed before the change, no drop below 90% coverage, thin
  API routes with logic in `application/`, no new way for a caller's filters to widen what policy
  allows, and no tokens, secrets, or raw sensitive queries in logs. Use synthetic data only.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the short version, and the
[specification](specification.md) for the full engineering contract.
