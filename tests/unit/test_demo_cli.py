"""`make demo` starts the offline service and opens the browser only once it is listening."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import runpy
from pathlib import Path

import pytest
import uvicorn

from agentic_context_service.demo import cli

POLICY_DATA = Path(__file__).parents[2] / "policies/context/data.json"


async def _no_sockets(self: uvicorn.Server, sockets: object = None) -> None:
    del self, sockets


def _server(opened: list[str], *, browser_found: bool = True) -> cli.BrowserOpeningServer:
    def opener(url: str) -> bool:
        opened.append(url)
        return browser_found

    config = uvicorn.Config(lambda: None, port=0)
    return cli.BrowserOpeningServer(config, "http://x/demo/", opener)


def test_should_use_the_documented_address_when_no_flags_are_given() -> None:
    # Given / When
    options = cli.parse_options([])

    # Then
    assert options.url == "http://127.0.0.1:8090/demo/"
    assert options.open_browser
    assert options.policy_data == Path("policies/context/data.json")


def test_should_skip_the_browser_when_asked_to() -> None:
    # Given / When
    options = cli.parse_options(["--no-browser", "--port", "8123"])

    # Then
    assert not options.open_browser
    assert options.url == "http://127.0.0.1:8123/demo/"


@pytest.mark.asyncio
async def test_should_open_the_page_when_the_server_has_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(uvicorn.Server, "startup", _no_sockets)
    opened: list[str] = []

    # When
    await _server(opened).startup()

    # Then
    assert opened == ["http://x/demo/"]


@pytest.mark.asyncio
async def test_should_print_the_address_to_open_when_no_browser_can_be_opened(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Given a machine with no browser, such as a server or a container
    monkeypatch.setattr(uvicorn.Server, "startup", _no_sockets)
    caplog.set_level("INFO", logger="agentic_context_service.demo")

    # When
    await _server([], browser_found=False).startup()

    # Then
    assert "No browser could be opened here. Open http://x/demo/ in a browser." in caplog.messages


@pytest.mark.asyncio
async def test_should_not_print_the_fallback_when_the_browser_opened(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Given
    monkeypatch.setattr(uvicorn.Server, "startup", _no_sockets)
    caplog.set_level("INFO", logger="agentic_context_service.demo")

    # When
    await _server([]).startup()

    # Then
    assert caplog.messages == ["Demo running at http://x/demo/ (press Ctrl+C to stop)"]


@pytest.mark.asyncio
async def test_should_neither_open_nor_warn_when_the_browser_is_turned_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Given
    monkeypatch.setattr(uvicorn.Server, "startup", _no_sockets)
    caplog.set_level("INFO", logger="agentic_context_service.demo")
    server = cli.BrowserOpeningServer(uvicorn.Config(lambda: None, port=0), "http://x/demo/", None)

    # When
    await server.startup()

    # Then
    assert caplog.messages == ["Demo running at http://x/demo/ (press Ctrl+C to stop)"]


@pytest.mark.asyncio
async def test_should_not_open_the_page_when_startup_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr(uvicorn.Server, "startup", _no_sockets)
    opened: list[str] = []
    server = _server(opened)
    server.should_exit = True

    # When
    await server.startup()

    # Then
    assert opened == []


def test_should_explain_how_to_run_it_when_the_policy_file_is_missing(
    tmp_path: Path,
) -> None:
    # Given
    missing = tmp_path / "nope.json"

    # When / Then
    with pytest.raises(SystemExit, match="repository root"):
        cli.main(["--no-browser", "--policy-data", str(missing)])


def test_should_build_and_serve_the_app_when_the_policy_file_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    served: list[int] = []
    opened: list[str] = []
    monkeypatch.setattr(uvicorn.Server, "startup", _no_sockets)
    monkeypatch.setattr("socket.create_server", _free)
    monkeypatch.setattr("webbrowser.open", opened.append)

    def fake_run(self: cli.BrowserOpeningServer) -> None:
        served.append(self.config.port)
        asyncio.run(self.startup())

    monkeypatch.setattr(cli.BrowserOpeningServer, "run", fake_run)

    # When
    cli.main(["--no-browser", "--policy-data", str(POLICY_DATA)])

    # Then
    assert served == [8090]
    assert opened == []


def test_should_pass_command_line_flags_when_run_as_a_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    received: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: received.append(list(argv)))
    monkeypatch.setattr("sys.argv", ["acs-demo", "--no-browser"])

    # When
    cli.entrypoint()

    # Then
    assert received == [["--no-browser"]]


def test_should_start_the_demo_when_run_as_a_module(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    calls: list[str] = []
    monkeypatch.setattr(cli, "entrypoint", lambda: calls.append("started"))

    # When
    runpy.run_module("agentic_context_service.demo", run_name="__main__")

    # Then
    assert calls == ["started"]


def _busy(address: tuple[str, int]) -> contextlib.AbstractContextManager[None]:
    raise OSError(errno.EADDRINUSE, f"{address} already in use")


def _free(address: tuple[str, int]) -> contextlib.AbstractContextManager[None]:
    del address
    return contextlib.nullcontext()


def test_should_say_how_to_pick_another_port_when_the_port_is_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setattr("socket.create_server", _busy)

    # When / Then
    with pytest.raises(SystemExit, match="Port 8090 is already in use"):
        cli.main(["--no-browser", "--policy-data", str(POLICY_DATA)])


def test_should_pass_other_bind_errors_through_when_they_are_not_a_busy_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    def denied(address: tuple[str, int]) -> contextlib.AbstractContextManager[None]:
        raise OSError(errno.EACCES, f"{address} permission denied")

    monkeypatch.setattr("socket.create_server", denied)

    # When / Then
    with pytest.raises(PermissionError):
        cli.main(["--no-browser", "--policy-data", str(POLICY_DATA)])
