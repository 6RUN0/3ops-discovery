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
from tools.snmp_fixtures import write_snmp_fixtures
from tools.stack_secrets import write_secrets

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
    host_journal: bool

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

    def relabel_targets_by_env(self, component: str, environment: str) -> int:
        """
        Count a relabel output's targets carrying environment=<environment>.

        File-provider targets (snmp) have no compose_project label, so
        relabel_project_targets would return 0. Scope by the provenance
        `environment` label the device fixture sets instead.
        """
        resp = requests.get(
            f"{self.alloy_url}/api/v0/web/components/{component}", timeout=10
        )
        resp.raise_for_status()
        count = 0
        for export in resp.json().get("exports", []):
            if export.get("name") != "output":
                continue
            for target in export["value"]["value"]:
                labels = {
                    p["key"]: p["value"]["value"] for p in target["value"]
                }
                if labels.get("environment") == environment:
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


@dataclass(frozen=True)
class _StackSpec:
    """
    What a caller chooses when bringing a stack variant up.

    Bundled into one object so ``_bring_up`` stays a 3-argument helper: the
    shared lifecycle is identical across variants, only these knobs differ.
    ``secrets_dir`` is created and populated by the caller before bring-up.
    """

    project: str
    optional: list[str]
    secrets_dir: Path
    extra_env: dict[str, str]
    extra_compose_files: list[str]
    host_journal: bool


def _bring_up(
    spec: _StackSpec,
    *,
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Stack]:
    """
    Bring the compose stack up, yield a ``Stack``, tear it down.

    Shared lifecycle for every e2e stack variant (main + snmp): ``spec``
    carries the overlay set, extra compose files, and extra env (secrets,
    device-dir); this owns materialize -> pre-clean -> up --build -d --wait ->
    readiness -> yield -> diagnostics-on-failure -> down -v.
    """
    config_dir = materialize(
        tmp_path_factory.mktemp("alloy-config"), optional=spec.optional
    )
    env = {
        **os.environ,
        "RU_3OPS_DISCOVERY_E2E_CONFIG_DIR": str(config_dir),
        "RU_3OPS_DISCOVERY_E2E_SECRETS_DIR": str(spec.secrets_dir),
        **spec.extra_env,
    }
    compose_files = [
        "-f",
        str(STACK_DIR / "docker-compose.yml"),
        *spec.extra_compose_files,
    ]
    compose_cmd = ("docker", "compose", "-p", spec.project, *compose_files)
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
        project=spec.project,
        compose_cmd=compose_cmd,
        env=env,
        prometheus_url=_compose_port(compose_cmd, env, "prometheus", 9090),
        loki_url=_compose_port(compose_cmd, env, "loki", 3100),
        alloy_url=_compose_port(compose_cmd, env, "alloy", 12345),
        host_journal=spec.host_journal,
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
        _collect_diagnostics(instance, ARTIFACTS_DIR / spec.project)
    subprocess.run(
        [*compose_cmd, "down", "-v"],
        env=env,
        capture_output=True,
        check=False,
    )


@pytest.fixture(scope="session")
def stack(
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Iterator[Stack]:
    if not _docker_ready():
        pytest.skip("docker daemon is not available; e2e needs it")

    host_journal = Path("/var/log/journal").is_dir()
    optional = ["060_otel.alloy", "070_host-metrics.alloy"]
    extra_compose_files: list[str] = []
    if host_journal:
        optional.append("080_host-logs.alloy")
        extra_compose_files = [
            "-f",
            str(STACK_DIR / "docker-compose.host-logs.yml"),
        ]
    secrets_dir = tmp_path_factory.mktemp("alloy-secrets")
    spec = _StackSpec(
        project=f"xad-e2e-{uuid.uuid4().hex[:8]}",
        optional=optional,
        secrets_dir=secrets_dir,
        extra_env=write_secrets(secrets_dir),
        extra_compose_files=extra_compose_files,
        host_journal=host_journal,
    )
    yield from _bring_up(
        spec, request=request, tmp_path_factory=tmp_path_factory
    )


@pytest.fixture(scope="session")
def snmp_stack(
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> Iterator[Stack]:
    if not _docker_ready():
        pytest.skip("docker daemon is not available; e2e needs it")

    snmp_dir = tmp_path_factory.mktemp("alloy-snmp")
    secrets_dir = tmp_path_factory.mktemp("alloy-snmp-secrets")
    # The device file (non-secret) goes in the writable snmp_dir; the auth
    # secret is written by write_secrets (real netmon-v3 creds), so pass empty
    # auths here -- the write_secrets spread below runs after this statement
    # and overwrites snmp_auths.yaml with the real profile.
    write_snmp_fixtures(
        snmp_dir,
        secrets_dir,
        devices=[
            {
                "name": "snmp-agent",
                "address": "snmp-agent:161",
                "module": "if_mib",
                "auth": "netmon-v3",
                "environment": "e2e",
                "team": "platform",
            },
            # Fail-closed negative: module outside the (if_mib) allowlist. The
            # discovery.relabel.snmp keep-rule MUST drop this row, so only the
            # valid device above survives (relabel_targets_by_env == 1).
            {
                "name": "snmp-bad-module",
                "address": "snmp-agent:161",
                "module": "no_such_mib",
                "auth": "netmon-v3",
                "environment": "e2e",
                "team": "platform",
            },
        ],
        auths={},
    )
    spec = _StackSpec(
        project=f"xad-snmp-{uuid.uuid4().hex[:8]}",
        optional=["037_snmp.alloy"],
        secrets_dir=secrets_dir,
        extra_env={
            "RU_3OPS_DISCOVERY_E2E_SNMP_DIR": str(snmp_dir),
            **write_secrets(secrets_dir),
        },
        extra_compose_files=[],
        host_journal=False,
    )
    yield from _bring_up(
        spec, request=request, tmp_path_factory=tmp_path_factory
    )
