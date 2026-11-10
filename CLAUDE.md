# CLAUDE.md — Agentic Context Service (`agentic-context-service`)

Canonical agent instructions for `gainratio/agentic-context-service`. Follow the executable contract in `docs/specification.md`. Preserve unrelated edits and never publish, push, create cloud resources, or use real customer data without explicit authorization.

## Status & Portfolio Pointers

- **Package version:** `0.1.0` (`pyproject.toml`, Python `>=3.13`, MIT)
- **Portfolio hub:** `https://open-source.gainratio.com/agentic-context-service/`
- **Portfolio engineering standard §8 (WASM):** Not applicable — Python 3.13 FastAPI service backed by OpenSearch, OPA, Redpanda, and PostgreSQL CDC; zero WASM modules.
- **Portfolio engineering standard §3.1–§3.4:**
  - **§3.1 (Trust gate):** Exercised across `tests/unit`, `tests/bdd`, `tests/integration`, and `opa test policies/` — fail-closed OPA policy evaluation, HMAC-SHA256 timestamped header signatures, replay/out-of-order CDC version guards, deletion tombstone retention, and tenant/purpose isolation.
  - **§3.2–§3.4:** N/A (retrieval service returning cited source chunks and freshness metadata rather than model-authored drafts, composite user scores, or PDF artifacts).

## Stack & Layout

- **Toolchain:** Python 3.13, `uv` (`uv.lock`), Poe the Poet (`poe verify` / `make verify`), Ruff (`format-check` + `lint-check`, max complexity 5), `mypy --strict`, `xenon` (`A/A/A`), `pytest` + `pytest-bdd` + `pytest-socket` (`>=90%` line and branch coverage), Bandit, `pip-audit`, Playwright UI tests (`package.json`), Dagger CI (`.dagger/`).
- **Source layout:**
  - `src/agentic_context_service/` — inward-facing domain/application ports, FastAPI HTTP surface, OpenSearch/OPA adapters, `testing` in-memory stand-ins, and `demo` app.
  - `policies/` — Rego policy bundle and 11,520-input parity suite against `testing.StaticPolicy`.
  - `packages/contracts/openapi.yaml` — OpenAPI 3 specification (no raw OpenSearch DSL exposed).
  - `deploy/compose/` & `connectors/` — PostgreSQL, Debezium, Redpanda, OpenSearch, and OPA local stack.
  - `examples/` — tested quickstart (`governed_retrieval.py`) and HTTP client (`ask_the_service.py`).

## Core Invariants

1. **Inward-facing domain & narrow Protocol ports.** Keep domain/application vendor-free; inject adapters via constructors and compose only at process entrypoints.
2. **Policy filters precede ranking and never widen.** Keep FastAPI routes thin; never expose raw OpenSearch DSL or allow caller filters to widen OPA constraints.
3. **Fail closed on policy or auth uncertainty.** Never log bearer tokens, HMAC signatures, secrets, or raw sensitive queries.
4. **Deterministic, externally versioned writes.** Checkpoint CDC consumers only after durable success; late/replayed events must never overwrite newer versions or resurrect tombstones.
5. **Honest AC reporting.** Report `AC-01` through `AC-20` honestly with exact evidence; never imply fixture evaluation proves live CDC.

## Quality Gates (Non-Negotiable)

Run `uv run poe verify` (or `make verify`) before every commit:

- **Scar (arm64 OPA SIGSEGV):** Pin multi-arch `openpolicyagent/opa:1.8.0-static` by index digest rather than amd64-only images that crashed under Apple Silicon emulation.
- **Scar (`expires_at` silent drop):** `POST /v1/memories` rejects non-future or naive `expires_at` timestamps with `400 INVALID_REQUEST` instead of storing already-expired records that vanish on search.
- **Scar (local `.env` polluting tests):** Test suites isolate settings from any developer `.env` so `make verify` stays green after `cp .env.example .env`.
- **Scar (README contract):** `tests/repository/test_readme_contract.py` pins `README.md` section order, real `governed_retrieval.py` output, link targets, and bans internal jargon words across the entire file.

## Commands

```sh
uv run poe verify      # full local gate: ruff, mypy, xenon A, unit, integration, bdd, bandit, pip-audit, eval
make demo              # launch offline multi-tenant browser demo (no Docker or API key)
make up && make seed   # start full Docker Compose CDC + OpenSearch + OPA stack (requires >=4 GiB Docker RAM)
```
