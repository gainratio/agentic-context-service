"""The `make up` preflight refuses a Docker VM too small for the local stack."""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest


def _load_preflight() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts/check_docker_memory.py"
    spec = importlib.util.spec_from_file_location("check_docker_memory_test_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the Docker memory preflight")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = _load_preflight()

GIB = 1024**3


def _reader(total: int) -> Callable[[], int]:
    return lambda: total


def test_threshold_is_three_and_a_half_gib_of_reported_memory() -> None:
    # Docker Desktop's "4 GB" setting reports about 3.8 GiB of MemTotal to the VM.
    assert preflight.MIN_REPORTED_BYTES == 3_758_096_384


def test_preflight_passes_a_docker_vm_with_four_gib(capsys: pytest.CaptureFixture[str]) -> None:
    assert preflight.main({}, _reader(int(3.8 * GIB))) == 0
    assert capsys.readouterr().err == ""


def test_preflight_refuses_a_small_docker_vm_with_a_clear_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = preflight.main({}, _reader(3_052_277_760))

    message = capsys.readouterr().err
    assert status == 1
    assert "Docker has 2.8 GiB of memory" in message
    assert "at least 4 GiB" in message
    assert "ACS_SKIP_MEMORY_CHECK=1" in message


def test_preflight_refuses_just_under_the_threshold() -> None:
    assert preflight.main({}, _reader(preflight.MIN_REPORTED_BYTES - 1)) == 1
    assert preflight.main({}, _reader(preflight.MIN_REPORTED_BYTES)) == 0


def test_override_skips_the_check_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    def never_called() -> int:
        raise AssertionError("docker must not be queried when the check is skipped")

    assert preflight.main({"ACS_SKIP_MEMORY_CHECK": "1"}, never_called) == 0
    assert "skipping the Docker memory check" in capsys.readouterr().err


def test_override_requires_the_exact_value_one() -> None:
    assert preflight.main({"ACS_SKIP_MEMORY_CHECK": "0"}, _reader(GIB)) == 1


def test_preflight_reports_docker_that_cannot_be_queried(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def docker_down() -> int:
        raise preflight.DockerMemoryUnavailableError("Cannot connect to the Docker daemon")

    assert preflight.main({}, docker_down) == 1
    assert "could not read Docker's memory" in capsys.readouterr().err


def test_reader_parses_docker_info(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert argv[1:] == ["info", "--format", "{{.MemTotal}}"]
        return subprocess.CompletedProcess(argv, 0, stdout="3052277760\n", stderr="")

    monkeypatch.setattr(preflight.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    assert preflight.docker_memory_bytes() == 3_052_277_760


@pytest.mark.parametrize(
    ("which", "outcome"),
    [
        (None, None),
        ("/usr/bin/docker", subprocess.CompletedProcess([], 1, stdout="", stderr="daemon down")),
        ("/usr/bin/docker", subprocess.CompletedProcess([], 0, stdout="lots\n", stderr="")),
    ],
    ids=["no-docker-cli", "daemon-down", "non-numeric"],
)
def test_reader_refuses_unusable_docker_info(
    monkeypatch: pytest.MonkeyPatch,
    which: str | None,
    outcome: subprocess.CompletedProcess[str] | None,
) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda _name: which)
    monkeypatch.setattr(preflight.subprocess, "run", lambda *_args, **_kwargs: outcome)

    with pytest.raises(preflight.DockerMemoryUnavailableError):
        preflight.docker_memory_bytes()
