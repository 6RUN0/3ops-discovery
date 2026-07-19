"""
E2e stack lifecycle: secrets, config materialization, docker compose.

The session fixture owns the whole lifecycle (compose up/down through
pytest fixtures): generate credentials into gitignored temp dirs,
materialize the config directory, pre-clean leftovers of a crashed run,
`up --build -d --wait`, poll readiness, yield, collect diagnostics on
failure, `down -v`.
"""

from __future__ import annotations

import json
import os
import secrets as pysecrets
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import pytest
import requests

from tools.materialize import materialize

STACK_DIR = Path(__file__).parent / "stack"
ARTIFACTS_DIR = Path(__file__).parent / "_artifacts"

#: Worst case to the FIRST metrics sample: 5s discovery refresh + 30s
#: normal-v1 scrape interval + remote_write flush + slack.
METRICS_BUDGET = 120.0
#: Logs stream continuously; their budget is tens of seconds.
LOGS_BUDGET = 60.0


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info"], capture_output=True, check=False
    )
    return probe.returncode == 0


def _endpoint_ok(url: str) -> bool:
    return requests.get(url, timeout=5).ok


class ReadinessTimeoutError(AssertionError):
    """A readiness or delivery predicate did not hold within budget."""


def wait_until[T](
    pred: Callable[[], T | None],
    timeout: float,
    desc: str,
    interval: float = 2.0,
) -> T:
    """Poll ``pred`` until it returns a truthy value or time runs out."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = pred()
        except (requests.RequestException, KeyError, ValueError) as exc:
            last_error = exc
        else:
            if result:
                return result
        time.sleep(interval)
    raise ReadinessTimeoutError(
        f"{desc}: not satisfied within {timeout}s"
        + (f" (last error: {last_error})" if last_error else "")
    )


@dataclass
class Stack:
    """Handles to the running e2e stack."""

    project: str
    compose_cmd: tuple[str, ...]
    env: dict[str, str]
    prometheus_url: str
    loki_url: str
    alloy_url: str

    def prom_query(self, expr: str) -> list[dict[str, Any]]:
        """Instant query; returns data.result (possibly empty)."""
        resp = requests.get(
            f"{self.prometheus_url}/api/v1/query",
            params={"query": expr},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        assert payload["status"] == "success", payload
        return list(payload["data"]["result"])

    def loki_entries(
        self, logql: str, *, since: str = "30m", limit: int = 5000
    ) -> list[tuple[str, str]]:
        """All (timestamp, line) entries for a LogQL query, paginated."""
        end_ns = time.time_ns()
        start_ns = end_ns - int(_to_seconds(since) * 1e9)
        entries: list[tuple[str, str]] = []
        while True:
            resp = requests.get(
                f"{self.loki_url}/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "start": str(start_ns),
                    "end": str(end_ns),
                    "limit": str(limit),
                    "direction": "forward",
                },
                timeout=30,
            )
            resp.raise_for_status()
            batch = [
                (value[0], value[1])
                for stream in resp.json()["data"]["result"]
                for value in stream["values"]
            ]
            entries.extend(batch)
            if len(batch) < limit:
                return entries
            # Advance past the newest returned timestamp.
            start_ns = max(int(ts) for ts, _line in batch) + 1

    def loki_series(self, match: str) -> list[dict[str, str]]:
        """Label sets of all streams matching the selector."""
        resp = requests.get(
            f"{self.loki_url}/loki/api/v1/series",
            params={"match[]": match, "since": "30m"},
            timeout=10,
        )
        resp.raise_for_status()
        return list(resp.json()["data"])

    def alloy_components(self) -> list[dict[str, Any]]:
        """Component list with health from the Alloy UI API."""
        resp = requests.get(
            f"{self.alloy_url}/api/v0/web/components", timeout=10
        )
        resp.raise_for_status()
        return list(resp.json())

    def relabel_project_targets(self, component: str) -> int:
        """
        Count a relabel output's targets belonging to this project.

        The shared Docker daemon exposes foreign enabled=true containers
        to discovery too, so the count is scoped to this run's
        compose_project label -- an unscoped count would be flaky.
        """
        resp = requests.get(
            f"{self.alloy_url}/api/v0/web/components/{component}", timeout=10
        )
        resp.raise_for_status()
        project_label = (
            "__meta_docker_container_label_com_docker_compose_project"
        )
        count = 0
        for export in resp.json().get("exports", []):
            if export.get("name") != "output":
                continue
            for target in export["value"]["value"]:
                labels = {
                    p["key"]: p["value"]["value"] for p in target["value"]
                }
                if labels.get(project_label) == self.project:
                    count += 1
        return count

    def compose_container(self, service: str) -> str:
        """Container name of a compose service."""
        return f"{self.project}-{service}-1"


def _to_seconds(duration: str) -> float:
    units = {"s": 1.0, "m": 60.0, "h": 3600.0}
    return float(duration[:-1]) * units[duration[-1]]


def _compose_port(
    compose_cmd: tuple[str, ...],
    env: dict[str, str],
    service: str,
    port: int,
) -> str:
    out = subprocess.run(
        [*compose_cmd, "port", service, str(port)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return f"http://{out}"


def _write_secrets(secrets_dir: Path) -> dict[str, str]:
    """
    Generate one credential source for the postgres pipeline.

    The DSN file and the container env come from the same values; the
    DSN host is the compose service name.
    """
    user = "xad_e2e"
    password = pysecrets.token_hex(16)
    secrets_dir.mkdir(parents=True, exist_ok=True)
    dsn = (
        f"postgresql://{user}:{password}@postgres:5432/postgres"
        "?sslmode=disable"
    )
    (secrets_dir / "postgres-orders.dsn").write_text(dsn, encoding="ascii")
    return {
        "RU_3OPS_DISCOVERY_E2E_PG_USER": user,
        "RU_3OPS_DISCOVERY_E2E_PG_PASSWORD": password,
    }


def _collect_diagnostics(stack: Stack, out_dir: Path) -> None:
    """Failure artifacts: files, not just stdout."""
    out_dir.mkdir(parents=True, exist_ok=True)
    logs = subprocess.run(
        [*stack.compose_cmd, "logs", "--tail=200"],
        env=stack.env,
        capture_output=True,
        text=True,
        check=False,
    )
    (out_dir / "compose-logs.txt").write_text(
        logs.stdout + logs.stderr, encoding="utf-8"
    )
    for name, url in (
        ("alloy-components.json", f"{stack.alloy_url}/api/v0/web/components"),
        ("prometheus-targets.json", f"{stack.prometheus_url}/api/v1/targets"),
    ):
        try:
            (out_dir / name).write_text(
                json.dumps(
                    requests.get(url, timeout=10).json(),
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except requests.RequestException as exc:
            (out_dir / name).write_text(str(exc), encoding="utf-8")


@pytest.fixture(scope="session")
def stack(
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Iterator[Stack]:
    if not _docker_ready():
        pytest.skip("docker daemon is not available; e2e needs it")

    project = f"xad-e2e-{uuid.uuid4().hex[:8]}"
    config_dir = materialize(tmp_path_factory.mktemp("alloy-config"))
    secrets_dir = tmp_path_factory.mktemp("alloy-secrets")
    env = {
        **os.environ,
        "RU_3OPS_DISCOVERY_E2E_CONFIG_DIR": str(config_dir),
        "RU_3OPS_DISCOVERY_E2E_SECRETS_DIR": str(secrets_dir),
        **_write_secrets(secrets_dir),
    }
    compose_cmd = (
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        str(STACK_DIR / "docker-compose.yml"),
    )
    # Pre-clean leftovers of a crashed previous run.
    subprocess.run(
        [*compose_cmd, "down", "-v", "--remove-orphans"],
        env=env,
        capture_output=True,
        check=False,
    )
    up = subprocess.run(
        [*compose_cmd, "up", "--build", "-d", "--wait"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if up.returncode != 0:
        subprocess.run(
            [*compose_cmd, "logs", "--tail=100"], env=env, check=False
        )
        subprocess.run(
            [*compose_cmd, "down", "-v"],
            env=env,
            capture_output=True,
            check=False,
        )
        pytest.fail(f"compose up failed:\n{up.stdout}\n{up.stderr}")

    instance = Stack(
        project=project,
        compose_cmd=compose_cmd,
        env=env,
        prometheus_url=_compose_port(compose_cmd, env, "prometheus", 9090),
        loki_url=_compose_port(compose_cmd, env, "loki", 3100),
        alloy_url=_compose_port(compose_cmd, env, "alloy", 12345),
    )
    for name, url in (
        ("prometheus", f"{instance.prometheus_url}/-/ready"),
        ("loki", f"{instance.loki_url}/ready"),
        ("alloy", f"{instance.alloy_url}/-/ready"),
    ):
        wait_until(
            partial(_endpoint_ok, url),
            timeout=60,
            desc=f"{name} readiness endpoint",
        )
    failures_before = request.session.testsfailed
    yield instance
    if request.session.testsfailed > failures_before:
        _collect_diagnostics(instance, ARTIFACTS_DIR / project)
    subprocess.run(
        [*compose_cmd, "down", "-v"],
        env=env,
        capture_output=True,
        check=False,
    )
