"""Regression tests for the executable local showcase."""

from __future__ import annotations

import importlib.util
import itertools
import urllib.error
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest


def _load_run_demo() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts/run_demo.py"
    spec = importlib.util.spec_from_file_location("run_demo_test_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load demo script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_demo = _load_run_demo()


def _result(record_id: str, source_version: str) -> dict[str, object]:
    return {
        "results": [
            {
                "content": "unrelated",
                "citation": {
                    "source_system": "catalog",
                    "record_id": record_id,
                    "source_version": source_version,
                },
                "source_facts": {
                    "kind": "retail_pricing_rule.v1",
                    "sku": record_id,
                    "max_discount_percent": 20,
                    "source_version": int(source_version),
                },
            }
        ]
    }


def test_await_version_requires_exact_target_citation(monkeypatch: pytest.MonkeyPatch) -> None:
    sequence: list[dict[str, object]] = [
        {"results": [], "metadata": {"version": "2"}},
        _result("OTHER-2", "2"),
        _result("NORTHSTAR-104", "12"),
        _result("NORTHSTAR-104", "2"),
    ]
    responses: Iterator[dict[str, object]] = iter(sequence)
    requests = 0

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal requests
        requests += 1
        assert path == "/v1/context:retrieve"
        assert payload == run_demo._retrieval()
        return next(responses)

    monkeypatch.setattr(run_demo, "_request", fake_request)
    monkeypatch.setattr(run_demo.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(run_demo.time, "sleep", lambda _seconds: None)

    response = run_demo._await_version("2")

    assert response == _result("NORTHSTAR-104", "2")
    assert requests == 4


def test_memory_create_uses_authenticated_demo_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        captured["path"] = path
        captured["payload"] = payload
        return {"id": "mem-1", "status": "created"}

    monkeypatch.setattr(run_demo, "_request", fake_request)

    run_demo._memory()

    assert captured["path"] == "/v1/memories"
    namespace = captured["payload"]["namespace"]
    assert namespace["user_id"] == "demo-analyst"


def test_memory_create_expires_in_the_future(monkeypatch: pytest.MonkeyPatch) -> None:
    # Search hides expired memories, so a fixed past expiry made step 6 time out forever.
    captured: dict[str, Any] = {}

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        captured["payload"] = payload
        return {"id": "mem-1", "status": "created"}

    monkeypatch.setattr(run_demo, "_request", fake_request)

    run_demo._memory()

    expires_at = datetime.fromisoformat(str(captured["payload"]["expires_at"]))
    remaining = expires_at - datetime.now(UTC)
    assert timedelta(hours=23) < remaining <= timedelta(days=1)


def test_await_memory_searches_namespace_until_created_id_is_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sequence: list[dict[str, object]] = [
        {"items": []},
        {"items": [{"document_id": "mem-other"}]},
        {
            "items": [
                {
                    "document_id": "mem-created",
                    "source": {
                        "content": {
                            "origin": "agent_derived",
                            "trust_class": "untrusted",
                            "proposed": True,
                        }
                    },
                }
            ]
        },
    ]
    responses: Iterator[dict[str, object]] = iter(sequence)
    payloads: list[dict[str, object]] = []

    def fake_request(path: str, payload: dict[str, object]) -> dict[str, object]:
        assert path == "/v1/memories:search"
        payloads.append(payload)
        return next(responses)

    monkeypatch.setattr(run_demo, "_request", fake_request)
    monkeypatch.setattr(run_demo.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(run_demo.time, "sleep", lambda _seconds: None)

    response = run_demo._await_memory("mem-created")

    assert response["items"][0]["document_id"] == "mem-created"
    assert len(payloads) == 3
    assert payloads[0]["query"] == "Prefer margin deltas as percentages."
    namespace = cast(dict[str, object], payloads[0]["namespace"])
    assert namespace["user_id"] == "demo-analyst"


def test_main_proves_created_memory_is_searchable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    initial = _result("NORTHSTAR-104", "1")
    initial_item = cast(dict[str, object], cast(list[object], initial["results"])[0])
    initial_citation = cast(dict[str, object], initial_item["citation"])
    initial_citation["source_uri"] = "postgres://retail/pricing_rules/NORTHSTAR-104"
    initial_item["freshness"] = {"age_seconds": 2}
    initial_item["component_ranks"] = {"lexical": 1, "semantic": 1}
    monkeypatch.setattr(run_demo, "_await_initial_context", lambda: initial)
    monkeypatch.setattr(run_demo, "_update_source", lambda: "2")
    monkeypatch.setattr(run_demo, "_await_version", lambda _version: _result("NORTHSTAR-104", "2"))
    monkeypatch.setattr(run_demo, "_deny_restricted", lambda: "explicitly denied")
    monkeypatch.setattr(
        run_demo,
        "_memory",
        lambda: {"id": "mem-created", "status": "created"},
    )
    searched: list[str] = []

    def fake_await_memory(memory_id: str) -> dict[str, object]:
        searched.append(memory_id)
        return {
            "items": [
                {
                    "document_id": memory_id,
                    "source": {
                        "content": {
                            "origin": "agent_derived",
                            "trust_class": "untrusted",
                            "proposed": True,
                        }
                    },
                }
            ]
        }

    monkeypatch.setattr(run_demo, "_await_memory", fake_await_memory)

    assert run_demo.main() == 0
    assert searched == ["mem-created"]
    assert "proposed, agent-derived, untrusted" in capsys.readouterr().out


def test_initial_context_requires_citation_freshness_and_component_ranks() -> None:
    valid = _result("NORTHSTAR-104", "1")
    item = cast(dict[str, object], cast(list[object], valid["results"])[0])
    item["citation"] = {
        "record_id": "NORTHSTAR-104",
        "source_system": "catalog",
        "source_version": "1",
        "source_uri": "postgres://retail/pricing_rules/NORTHSTAR-104",
    }
    item["freshness"] = {"age_seconds": 2}
    item["component_ranks"] = {"lexical": 1, "semantic": 1}

    assert run_demo._has_initial_context(valid) is True
    assert run_demo._has_initial_context({"results": []}) is False


def _valid_initial_context() -> dict[str, object]:
    valid = _result("NORTHSTAR-104", "1")
    item = cast(dict[str, object], cast(list[object], valid["results"])[0])
    item["citation"] = {
        "source_system": "catalog",
        "record_id": "NORTHSTAR-104",
        "source_version": "1",
        "source_uri": "postgres://retail/pricing_rules/NORTHSTAR-104",
    }
    item["freshness"] = {"age_seconds": 2}
    item["component_ranks"] = {"lexical": 1, "semantic": 1}
    return valid


def test_await_initial_context_retries_until_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    valid = _valid_initial_context()
    responses = iter([{"results": []}, valid])
    monkeypatch.setattr(run_demo, "_request", lambda *_args: next(responses))
    monkeypatch.setattr(run_demo.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(run_demo.time, "sleep", lambda _seconds: None)

    assert run_demo._await_initial_context() == valid


@pytest.mark.parametrize(
    "transient",
    [
        TimeoutError("timed out"),
        urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")),
    ],
)
def test_await_initial_context_retries_while_the_api_warms_up(
    monkeypatch: pytest.MonkeyPatch, transient: OSError
) -> None:
    # A fresh API loads its embedding model on the first query, which can outlast one request.
    valid = _valid_initial_context()
    failures = iter([transient])

    def flaky_request(*_args: object) -> dict[str, object]:
        failure = next(failures, None)
        if failure is not None:
            raise failure
        return valid

    monkeypatch.setattr(run_demo, "_request", flaky_request)
    monkeypatch.setattr(run_demo.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(run_demo.time, "sleep", lambda _seconds: None)

    assert run_demo._await_initial_context() == valid


_RUNAWAY_LIMIT = 50


def _stall_the_api(monkeypatch: pytest.MonkeyPatch, failure: Exception | None = None) -> None:
    # The fake clock jumps 10 s per read, so a loop that honours its deadline stops after a few
    # calls. A loop that ignores it hits the runaway limit and fails fast instead of hanging.
    calls = itertools.count(1)
    clock = itertools.count(0.0, 10.0)

    def stalled_request(*_args: object) -> dict[str, object]:
        if next(calls) > _RUNAWAY_LIMIT:
            raise AssertionError("polling loop ignored its deadline")
        if failure is not None:
            raise failure
        return {"results": [], "items": []}

    monkeypatch.setattr(run_demo, "_request", stalled_request)
    monkeypatch.setattr(run_demo.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(run_demo.time, "sleep", lambda _seconds: None)


def test_await_initial_context_gives_up_after_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stall_the_api(monkeypatch, TimeoutError("timed out"))

    with pytest.raises(TimeoutError, match="initial hybrid retrieval"):
        run_demo._await_initial_context()


def test_await_version_gives_up_after_its_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    _stall_the_api(monkeypatch)

    with pytest.raises(TimeoutError, match="CDC source version 2"):
        run_demo._await_version("2")


def test_await_memory_gives_up_after_its_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    _stall_the_api(monkeypatch)

    with pytest.raises(TimeoutError, match="mem-1 was not searchable"):
        run_demo._await_memory("mem-1")


def test_await_initial_context_surfaces_http_errors_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A real API answer (401, 500) is not warm-up; hiding it would mask auth or policy bugs.
    denied = urllib.error.HTTPError("http://localhost:8080", 401, "Unauthorized", Message(), None)

    def rejects(*_args: object) -> dict[str, object]:
        raise denied

    clock = iter([0.0, 0.0, 61.0])
    monkeypatch.setattr(run_demo, "_request", rejects)
    monkeypatch.setattr(run_demo.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(run_demo.time, "sleep", lambda _seconds: None)

    with pytest.raises(urllib.error.HTTPError):
        run_demo._await_initial_context()
