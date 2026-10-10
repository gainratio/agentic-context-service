"""Refuse `make up` early when Docker has too little memory for the local stack."""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
import sys
from collections.abc import Callable, Mapping
from typing import Final

GIB: Final = 1024**3
# Docker Desktop's "4 GB" setting reports about 3.8 GiB of MemTotal, so the check allows for
# that kernel overhead while still refusing VMs like the 2.8 GiB one where Debezium was OOM-killed.
MIN_REPORTED_BYTES: Final = 3 * GIB + GIB // 2
SKIP_VARIABLE: Final = "ACS_SKIP_MEMORY_CHECK"


class DockerMemoryUnavailableError(RuntimeError):
    """Docker's memory total could not be read."""


def docker_memory_bytes() -> int:
    executable = shutil.which("docker")
    if executable is None:
        raise DockerMemoryUnavailableError("the docker command is not on PATH")
    # Fixed argv; no shell expansion is used.
    result = subprocess.run(  # nosec B603
        [executable, "info", "--format", "{{.MemTotal}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    total = result.stdout.strip()
    if result.returncode != 0 or not total.isdigit():
        raise DockerMemoryUnavailableError(result.stderr.strip() or f"unexpected output {total!r}")
    return int(total)


def main(
    environ: Mapping[str, str] = os.environ,
    read_total: Callable[[], int] = docker_memory_bytes,
) -> int:
    if environ.get(SKIP_VARIABLE) == "1":
        _say(f"{SKIP_VARIABLE}=1: skipping the Docker memory check; the stack may be OOM-killed.")
        return 0
    try:
        total = read_total()
    except DockerMemoryUnavailableError as error:
        _say(f"make up: could not read Docker's memory ({error}). Is Docker running?")
        return 1
    if total < MIN_REPORTED_BYTES:
        _say(_too_small(total))
        return 1
    return 0


def _too_small(total: int) -> str:
    return (
        f"make up: Docker has {total / GIB:.1f} GiB of memory; the local stack needs at least"
        " 4 GiB (Docker Desktop: Settings > Resources > Memory). To try anyway, run"
        f" `{SKIP_VARIABLE}=1 make up`."
    )


def _say(message: str) -> None:
    print(message, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
