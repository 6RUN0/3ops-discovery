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

from tools.backends import (
    BACKEND_NAMES,
    LogQuery,
    LogRecord,
    LogsBackend,
    LokiBackend,
    VictoriaLogsBackend,
    selected_backend,
)
from tools.materialize import COMBOS, materialize
from tools.snmp_fixtures import write_snmp_fixtures
from tools.stack_secrets import write_secrets

STACK_DIR = Path(__file__).parent / "stack"
#: Value the main stack passes as RU_3OPS_DISCOVERY_HOSTNAME; deliberately
#: unlike any container hostname, so a fallback cannot satisfy a check.
E2E_HOSTNAME = "e2e-collector"
ARTIFACTS_DIR = Path(__file__).parent / "_artifacts"

#: Worst case to the FIRST metrics sample: 5s discovery refresh + 30s
#: normal-v1 scrape interval + remote_write flush + slack.
METRICS_BUDGET = 120.0
#: Logs stream continuously; their budget is tens of seconds.
LOGS_BUDGET = 60.0
#: systemd in journal-host reaches `running` in about a second on an idle
#: host; the rest is headroom for a loaded runner.
JOURNAL_HOST_BOOT_BUDGET = 120.0
#: One `is-system-running --wait` call; well below the budget, so a hung
#: call is retried and reported instead of eating the whole budget.
JOURNAL_HOST_ATTEMPT_TIMEOUT = 30.0
#: Service that runs systemd as PID 1 and owns the journal 080 reads.
JOURNAL_HOST = "journal-host"
#: e2e-only overlay adding journal-host (read-write host cgroup mount);
#: every e2e fixture passes it, `nox -s demo` never does.
JOURNAL_HOST_COMPOSE = STACK_DIR / "docker-compose.journal-host.yml"


@dataclass(frozen=True)
class BackendSpec:
    """
    How one storage variant plugs into the compose stack.

    compose_files: extra `-f` arguments layered over the base compose file.
    metrics_service / logs_service: compose services whose published ports
        serve the Prometheus query API and the log query API.
    *_ready_path: HTTP path answering 2xx once the store accepts queries.
    logs_factory: builds the `LogsBackend` from the logs base URL.
    """

    compose_files: tuple[str, ...]
    metrics_service: str
    metrics_port: int
    metrics_ready_path: str
    logs_service: str
    logs_port: int
    logs_ready_path: str
    logs_factory: Callable[[str], LogsBackend]


BACKENDS: dict[str, BackendSpec] = {
    "prometheus-loki": BackendSpec(
        compose_files=(),
        metrics_service="prometheus",
        metrics_port=9090,
        metrics_ready_path="/-/ready",
        logs_service="loki",
        logs_port=3100,
        logs_ready_path="/ready",
        logs_factory=LokiBackend,
    ),
    "victoria": BackendSpec(
        compose_files=("-f", str(STACK_DIR / "docker-compose.victoria.yml")),
        metrics_service="victoriametrics",
        metrics_port=8428,
        metrics_ready_path="/health",
        logs_service="victorialogs",
        logs_port=9428,
        logs_ready_path="/health",
        logs_factory=VictoriaLogsBackend,
    ),
}
if set(BACKENDS) != set(BACKEND_NAMES):
    raise RuntimeError(
        f"conftest BACKENDS {sorted(BACKENDS)} != "
        f"tools.backends.BACKEND_NAMES {sorted(BACKEND_NAMES)}"
    )

_BACKEND_KEY = pytest.StashKey[str]()


def pytest_configure(config: pytest.Config) -> None:
    """Resolve the storage variant once, before collection touches docker."""
    try:
        config.stash[_BACKEND_KEY] = selected_backend(os.environ)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc


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
    """Poll `pred` until it returns a truthy value or time runs out."""
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
    """
    Handles to the running e2e stack.

    Both session-scoped stacks share one Docker daemon, and log discovery
    is unfiltered by contract (logs are collected by default). So Alloy of
    stack A really does read the containers of stack B into its own log
    store, and both stacks are built from the SAME compose file -- the
    container names are identical. Isolation therefore rests on the
    promoted compose_project label, which `logs` enforces at the door
    (`tools.backends.check_scope`) rather than at each call site.
    """

    project: str
    compose_cmd: tuple[str, ...]
    env: dict[str, str]
    metrics_url: str
    logs: LogsBackend
    backend: str
    alloy_url: str

    def prom_query(self, expr: str) -> list[dict[str, Any]]:
        """Instant PromQL query; returns data.result (possibly empty)."""
        resp = requests.get(
            f"{self.metrics_url}/api/v1/query",
            params={"query": expr},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        assert payload["status"] == "success", payload
        return list(payload["data"]["result"])

    def log_records(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[LogRecord]:
        """All records matching the query, ascending by timestamp."""
        return self.logs.records(query, since=since)

    def log_entries(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[tuple[str, str]]:
        """All (timestamp, line) entries matching the query."""
        return self.logs.entries(query, since=since)

    def log_streams(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[dict[str, str]]:
        """Label sets of all streams matching the query's selector."""
        return self.logs.streams(query, since=since)

    def alloy_components(self) -> list[dict[str, Any]]:
        """Component list with health from the Alloy UI API."""
        resp = requests.get(
            f"{self.alloy_url}/api/v0/web/components", timeout=10
        )
        resp.raise_for_status()
        return list(resp.json())

    def relabel_target_labels(self, component: str) -> list[dict[str, str]]:
        """
        Label maps of a relabel output's targets belonging to this project.

        The shared Docker daemon exposes foreign enabled=true containers
        to discovery too, so the result is scoped to this run's
        compose_project label -- an unscoped read would be flaky. Unlike
        the counting helpers, this returns the raw label dicts so tests
        can assert on label VALUES (profile routing, provenance) and on
        container-name membership.
        """
        resp = requests.get(
            f"{self.alloy_url}/api/v0/web/components/{component}", timeout=10
        )
        resp.raise_for_status()
        project_label = (
            "__meta_docker_container_label_com_docker_compose_project"
        )
        found = []
        for export in resp.json().get("exports", []):
            if export.get("name") != "output":
                continue
            for target in export["value"]["value"]:
                labels = {
                    p["key"]: p["value"]["value"] for p in target["value"]
                }
                if labels.get(project_label) == self.project:
                    found.append(labels)
        return found

    def relabel_project_targets(self, component: str) -> int:
        """Count a relabel output's targets belonging to this project."""
        return len(self.relabel_target_labels(component))

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

    def compose_exec(
        self, service: str, *argv: str, timeout: float = 60.0
    ) -> subprocess.CompletedProcess[str]:
        """Run `argv` in a running service; output captured, no check."""
        return subprocess.run(
            [*self.compose_cmd, "exec", "-T", service, *argv],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )


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
    sources = [
        ("alloy-components.json", f"{stack.alloy_url}/api/v0/web/components"),
    ]
    if stack.backend == "prometheus-loki":
        sources.append(
            ("prometheus-targets.json", f"{stack.metrics_url}/api/v1/targets")
        )
    for name, url in sources:
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
    if stack.backend == "victoria":
        _write_victorialogs_streams(
            stack, out_dir / "victorialogs-streams.json"
        )
    _write_journal_host_state(stack, out_dir)


def _write_journal_host_state(stack: Stack, out_dir: Path) -> None:
    """Dump journal-host container state, failed units and journal tail."""
    (out_dir / "journal-host-container.txt").write_text(
        _journal_host_container_report(stack), encoding="utf-8"
    )
    for name, argv in (
        (
            "journal-host-failed-units.txt",
            ("systemctl", "--failed", "--no-pager"),
        ),
        (
            "journal-host-journal.txt",
            ("journalctl", "--no-pager", "-n", "300"),
        ),
    ):
        try:
            proc = stack.compose_exec(JOURNAL_HOST, *argv, timeout=30)
            text = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as exc:
            text = str(exc)
        (out_dir / name).write_text(text, encoding="utf-8")


class JournalHostBootError(AssertionError):
    """journal-host exited or did not finish booting within budget."""


def _journal_host_status(stack: Stack) -> tuple[str, str]:
    """Return (state status, exit code) of the journal-host container."""
    try:
        proc = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}} {{.State.ExitCode}}",
                stack.compose_container(JOURNAL_HOST),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        # Called from boot readiness and diagnostics: a hung daemon must
        # surface as a status, not replace the boot error being reported.
        return ("unknown (docker inspect timed out after 30s)", "?")
    status, _, code = proc.stdout.strip().partition(" ")
    return (status or f"unknown ({proc.stderr.strip()})", code or "?")


def _journal_host_container_report(stack: Stack) -> str:
    """Container status, exit code and `docker logs` tail as one text."""
    status, code = _journal_host_status(stack)
    try:
        logs = subprocess.run(
            [
                "docker",
                "logs",
                "--tail=50",
                stack.compose_container(JOURNAL_HOST),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        tail = logs.stdout + logs.stderr
    except subprocess.TimeoutExpired:
        tail = "docker logs timed out after 30s\n"
    return (
        f"status={status} exit_code={code}\n"
        f"--- docker logs --tail=50 ---\n{tail}"
    )


def _journal_host_state(stack: Stack, last_error: list[str]) -> str | None:
    """
    Return the boot state once startup settles; None to retry.

    Raises JournalHostBootError at once when the container is not running:
    an exec into an exited container fails instantly and would otherwise
    spin until the budget runs out.
    """
    # Right after `up` the manager's private socket may not exist yet and
    # systemctl fails at once; `--wait` then blocks until startup finishes.
    try:
        proc = stack.compose_exec(
            JOURNAL_HOST,
            "systemctl",
            "is-system-running",
            "--wait",
            timeout=JOURNAL_HOST_ATTEMPT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        last_error[:] = [
            f"is-system-running --wait timed out after "
            f"{JOURNAL_HOST_ATTEMPT_TIMEOUT}s"
        ]
        return None
    state = proc.stdout.strip()
    if state in ("running", "degraded"):
        return state
    last_error[:] = [f"state={state!r} stderr={proc.stderr.strip()!r}"]
    status, _code = _journal_host_status(stack)
    if status != "running":
        raise JournalHostBootError(
            f"{JOURNAL_HOST} is not running; {last_error[0]}\n"
            + _journal_host_container_report(stack)
        )
    return None


def _wait_journal_host(stack: Stack) -> None:
    """Block until journal-host booted; record failed units if degraded."""
    last_error: list[str] = []
    try:
        state = wait_until(
            partial(_journal_host_state, stack, last_error),
            timeout=JOURNAL_HOST_BOOT_BUDGET,
            desc=f"{JOURNAL_HOST} systemd boot finished",
        )
    except ReadinessTimeoutError as exc:
        raise JournalHostBootError(
            f"{exc}; last attempt: {last_error[0] if last_error else '-'}\n"
            + _journal_host_container_report(stack)
        ) from exc
    if state == "degraded":
        out_dir = ARTIFACTS_DIR / stack.project
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_journal_host_state(stack, out_dir)


def _write_victorialogs_streams(stack: Stack, path: Path) -> None:
    """Dump this project's VictoriaLogs streams for a failed run."""
    try:
        streams = stack.log_streams(
            LogQuery(stream={"compose_project": stack.project})
        )
        path.write_text(
            json.dumps(streams, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except (requests.RequestException, ValueError) as exc:
        path.write_text(str(exc), encoding="utf-8")


@dataclass(frozen=True)
class _StackSpec:
    """
    What a caller chooses when bringing a stack variant up.

    Bundled into one object so `_bring_up` stays a 3-argument helper: the
    shared lifecycle is identical across variants, only these knobs differ.
    `secrets_dir` is created and populated by the caller before bring-up.
    """

    project: str
    domains: tuple[str, ...]
    secrets_dir: Path
    extra_env: dict[str, str]
    backend: str


def _bring_up(
    spec: _StackSpec,
    *,
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Stack]:
    """
    Bring the compose stack up, yield a `Stack`, tear it down.

    Shared lifecycle for every e2e stack variant (main + snmp): `spec`
    carries the domain set and extra env (secrets, device-dir); this owns
    materialize -> pre-clean -> up --build -d --wait -> readiness (journal-host
    boot included) -> yield -> diagnostics-on-failure -> down -v.
    """
    config_dir = materialize(
        tmp_path_factory.mktemp("alloy-config"), spec.domains
    )
    env = {
        **os.environ,
        "RU_3OPS_DISCOVERY_E2E_CONFIG_DIR": str(config_dir),
        "RU_3OPS_DISCOVERY_E2E_SECRETS_DIR": str(spec.secrets_dir),
        **spec.extra_env,
    }
    backend = BACKENDS[spec.backend]
    compose_files = [
        "-f",
        str(STACK_DIR / "docker-compose.yml"),
        "-f",
        str(JOURNAL_HOST_COMPOSE),
        *backend.compose_files,
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

    # From here on the stack runs: any failure, before or after the yield,
    # must still reach `down -v`, or the privileged journal-host leaks.
    try:
        metrics_url = _compose_port(
            compose_cmd, env, backend.metrics_service, backend.metrics_port
        )
        logs_url = _compose_port(
            compose_cmd, env, backend.logs_service, backend.logs_port
        )
        instance = Stack(
            project=spec.project,
            compose_cmd=compose_cmd,
            env=env,
            metrics_url=metrics_url,
            logs=backend.logs_factory(logs_url),
            backend=spec.backend,
            alloy_url=_compose_port(compose_cmd, env, "alloy", 12345),
        )
        try:
            for name, url in (
                (
                    backend.metrics_service,
                    f"{metrics_url}{backend.metrics_ready_path}",
                ),
                (backend.logs_service, f"{logs_url}{backend.logs_ready_path}"),
                ("alloy", f"{instance.alloy_url}/-/ready"),
            ):
                wait_until(
                    partial(_endpoint_ok, url),
                    timeout=60,
                    desc=f"{name} readiness endpoint",
                )
            _wait_journal_host(instance)
        except BaseException:
            _collect_diagnostics(instance, ARTIFACTS_DIR / spec.project)
            raise
        failures_before = request.session.testsfailed
        yield instance
        if request.session.testsfailed > failures_before:
            _collect_diagnostics(instance, ARTIFACTS_DIR / spec.project)
    finally:
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

    secrets_dir = tmp_path_factory.mktemp("alloy-secrets")
    spec = _StackSpec(
        project=f"xad-e2e-{uuid.uuid4().hex[:8]}",
        domains=COMBOS["all"],
        secrets_dir=secrets_dir,
        extra_env={
            "RU_3OPS_DISCOVERY_HOSTNAME": E2E_HOSTNAME,
            **write_secrets(secrets_dir),
        },
        backend=request.config.stash[_BACKEND_KEY],
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
            # Same agent through the system module: one device row per
            # module, so the second module is a second row with its own name.
            {
                "name": "snmp-agent-system",
                "address": "snmp-agent:161",
                "module": "system",
                "auth": "netmon-v3",
                "environment": "e2e",
                "team": "platform",
            },
            # Fail-closed negative: module outside the (if_mib|system)
            # allowlist. The discovery.relabel.snmp keep-rule MUST drop this
            # row, so only the two valid devices above survive
            # (relabel_targets_by_env == 2).
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
    # The all-snmp combination, not snmp alone: the main fixture runs every
    # other domain, so only this stack loads snmp merged with the rest
    # outside `validate`.
    spec = _StackSpec(
        project=f"xad-snmp-{uuid.uuid4().hex[:8]}",
        domains=COMBOS["all-snmp"],
        secrets_dir=secrets_dir,
        extra_env={
            # Empty overrides an inherited value: this stack pins the
            # collector-hostname fallback.
            "RU_3OPS_DISCOVERY_HOSTNAME": "",
            "RU_3OPS_DISCOVERY_E2E_SNMP_DIR": str(snmp_dir),
            **write_secrets(secrets_dir),
        },
        backend=request.config.stash[_BACKEND_KEY],
    )
    yield from _bring_up(
        spec, request=request, tmp_path_factory=tmp_path_factory
    )
