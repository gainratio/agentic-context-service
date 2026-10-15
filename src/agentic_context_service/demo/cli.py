"""`make demo`: start the offline service and open its page in your browser."""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import uvicorn

from agentic_context_service.demo.app import create_demo_app

DEFAULT_PORT: Final = 8090
DEFAULT_POLICY_DATA: Final = Path("policies/context/data.json")
_log = logging.getLogger("agentic_context_service.demo")


class BrowserOpeningServer(uvicorn.Server):
    """A uvicorn server that opens the demo page once it is accepting connections."""

    def __init__(self, config: uvicorn.Config, url: str, opener: Callable[[str], object]) -> None:
        super().__init__(config)
        self._url = url
        self._opener = opener

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        if not self.should_exit:
            _log.info("Demo running at %s (press Ctrl+C to stop)", self._url)
            self._opener(self._url)


@dataclass(frozen=True, slots=True)
class DemoOptions:
    host: str
    port: int
    open_browser: bool
    policy_data: Path

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/demo/"


def parse_options(argv: Sequence[str]) -> DemoOptions:
    """Read the command-line flags."""
    parser = argparse.ArgumentParser(prog="acs-demo", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument("--policy-data", type=Path, default=DEFAULT_POLICY_DATA)
    args = parser.parse_args(argv)
    return DemoOptions(args.host, args.port, not args.no_browser, args.policy_data)


def main(argv: Sequence[str]) -> None:
    """Build the offline demo and serve it until interrupted."""
    options = parse_options(argv)
    if not options.policy_data.is_file():
        raise SystemExit(
            f"{options.policy_data} not found. Run `make demo` from the repository root."
        )
    app = create_demo_app(options.policy_data)
    config = uvicorn.Config(app, host=options.host, port=options.port)
    opener = webbrowser.open if options.open_browser else _skip_browser
    BrowserOpeningServer(config, options.url, opener).run()


def _skip_browser(url: str) -> None:
    del url


def entrypoint() -> None:
    """Console-script entry point (`uv run acs-demo`)."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main(sys.argv[1:])
