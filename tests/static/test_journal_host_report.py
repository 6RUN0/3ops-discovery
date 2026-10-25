"""
journal-host diagnostics survive a hung docker daemon.

The status and report helpers run while a boot failure is being reported;
a `docker inspect`/`docker logs` timeout escaping there as `TimeoutExpired`
would replace the boot error the operator needs to see.
"""

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from tests.e2e import conftest as e2e


def _hung_docker(
    *_args: Any, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    raise subprocess.TimeoutExpired(cmd="docker", timeout=kwargs["timeout"])


def _stack() -> Any:
    return SimpleNamespace(compose_container=lambda service: f"p-{service}-1")


def test_status_reports_inspect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung `docker inspect` becomes an unknown status, not an exception."""
    monkeypatch.setattr(subprocess, "run", _hung_docker)
    status, code = e2e._journal_host_status(_stack())
    assert status == "unknown (docker inspect timed out after 30s)"
    assert code == "?"


def test_report_survives_logs_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung `docker logs` still yields a report naming the timeout."""
    monkeypatch.setattr(subprocess, "run", _hung_docker)
    report = e2e._journal_host_container_report(_stack())
    assert "status=unknown (docker inspect timed out after 30s)" in report
    assert "docker logs timed out after 30s" in report
