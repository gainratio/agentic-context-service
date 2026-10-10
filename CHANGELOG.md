# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic
versioning.

## [Unreleased]

### Added

- Initial governed context-plane contracts, deterministic retail fixtures, OPA policy, local
  Compose topology, evaluation evidence, threat model, operations guide, and architecture ADRs.
- Offline quickstart example (`examples/quickstart/governed_retrieval.py`) and a README contract
  test that pins the first screen, links, and the example's real output.

### Changed

- README follows the portfolio template; the package description is now the README tagline.

### Fixed

- The local quickstart (`make up && make seed && make demo`) works again on Apple silicon: OPA
  now runs the multi-arch `openpolicyagent/opa:1.8.0-static` image natively instead of the
  amd64-only image under emulation, where it crashed with SIGSEGV and stayed unhealthy.
- `make demo` step 6 no longer creates a memory that has already expired, and step 1 waits
  through the API's cold first query instead of failing on a 10-second socket timeout.
- `make` targets ignore another project's activated `VIRTUAL_ENV`.
- The test suite ignores a developer's local `.env`, so `make verify` passes after the
  quickstart's `cp .env.example .env`.

### Changed

- `POST /v1/memories` rejects an `expires_at` that is not a future, timezone-qualified instant
  with `400 INVALID_REQUEST`. It previously stored the memory, answered `created`, and then never
  returned it from search.
