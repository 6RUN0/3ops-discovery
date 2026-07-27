"""
Nox sessions for the 3ops Discovery quality gates.

``default_venv_backend = "none"``: nox creates no environments of its
own, every tool runs through ``uv run`` (single source of versions is
uv.lock). Default run = lint + docs_lint + alloy_check + tests; the
default honestly needs Docker (alloy_check) and network (lychee) and
fails loudly without them -- the fully offline set is
``nox -s lint tests``.

    uv run nox                  # default gates
    uv run nox -s lint          # pre-commit hooks on all files
    uv run nox -s tests         # static consistency + mini-app units
    uv run nox -s e2e           # docker compose delivery checks
    uv run nox -s preflight     # everything
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import nox

REPO = Path(__file__).parent
sys.path.insert(0, str(REPO))

nox.options.default_venv_backend = "none"
nox.options.sessions = ["lint", "docs_lint", "alloy_check", "tests"]

#: Exactly the tag pinned by the manifest (section 14): foreach is
#: experimental and its semantics may drift between Alloy versions.
#: tests/static/test_reference_files.py asserts this equality.
ALLOY_IMAGE = "grafana/alloy:v1.17.1"


def _uv(session: nox.Session, *args: str) -> None:
    session.run("uv", "run", *args, external=True)


@nox.session
def lint(session: nox.Session) -> None:
    """Run every pre-commit hook against all files."""
    _uv(session, "pre-commit", "run", "--all-files", "--show-diff-on-failure")


#: docs_lint runs system binaries (see CLAUDE.md for the install
#: hints); a missing tool is a loud error, not a silent skip.
_DOCS_LINT_TOOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rumdl", ("check", ".")),
    ("typos", ()),
    ("lychee", ("--no-progress", ".")),
)


@nox.session
def docs_lint(session: nox.Session) -> None:
    """Lint markdown: structure (rumdl), spelling (typos), links (lychee)."""
    for tool, args in _DOCS_LINT_TOOLS:
        if shutil.which(tool) is None:
            session.error(
                f"{tool} is required for docs_lint and is not on PATH"
            )
        session.run(tool, *args, external=True)


#: `alloy fmt -t` exits 0 when the file is already canonical and 1 when
#: it is not. Anything else is docker never running the check at all --
#: 125 for an image it cannot pull, for one.
_FMT_CANONICAL = 0
_FMT_NEEDS_CHANGE = 1


class AlloyFmtError(RuntimeError):
    """docker could not run the formatter, so the file was never checked."""


def alloy_config_mount(config_dir: Path) -> str:
    """
    Return the ``-v`` argument mounting a config dir read-only.

    The path must be absolute. Docker reads a RELATIVE source as a
    NAMED VOLUME rather than a host directory and rejects it ("includes
    invalid characters for a local volume name"), which is exactly how
    CI broke while a laxer local docker accepted `.nox/...` happily.
    """
    if not config_dir.is_absolute():
        raise ValueError(
            f"the config mount source must be absolute, got {config_dir}"
        )
    return f"{config_dir}:/etc/alloy:ro"


def alloy_fmt_verdict(returncode: int, stderr: str) -> bool:
    """
    Return True if the file needs reformatting; raise if docker failed.

    Reading every non-zero code as "unformatted" once made CI report all
    seven base files as broken on a runner that never obtained the
    image: an infrastructure failure wearing a formatting failure's
    clothes, with the real cause captured and dropped.
    """
    if returncode in (_FMT_CANONICAL, _FMT_NEEDS_CHANGE):
        return returncode == _FMT_NEEDS_CHANGE
    raise AlloyFmtError(
        f"docker exited {returncode} running `alloy fmt -t`, so nothing "
        f"was verified: {stderr.strip() or '<no stderr>'}"
    )


def _alloy_fmt_would_change(config_dir: Path, name: str) -> bool:
    """
    Return True if ``alloy fmt`` would reformat the named file.

    Uses ``fmt -t`` (non-mutating): nothing is written back.
    """
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            alloy_config_mount(config_dir),
            ALLOY_IMAGE,
            "fmt",
            "-t",
            f"/etc/alloy/{name}",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    return alloy_fmt_verdict(result.returncode, result.stderr)


@nox.session
def alloy_check(session: nox.Session) -> None:
    """
    Fmt (non-mutating -t) + validate for every directory combination.

    Combinations come from tools.materialize.COMBOS; each is
    materialized into a temp dir and mounted as one read-only volume,
    exercising the same overlay mechanism the e2e stack uses.
    """
    from tools.materialize import COMBOS, materialize
    from tools.snmp_fixtures import write_snmp_fixtures

    if shutil.which("docker") is None:
        session.error("docker is required for alloy_check")
    # Pull once, up front and visibly. The fmt checks capture their
    # output, so an image fetched lazily inside them would fail with the
    # reason hidden; here a registry problem is reported as one.
    session.run("docker", "pull", ALLOY_IMAGE, external=True)
    for combo, optional in COMBOS.items():
        # resolve(): create_tmp() hands back a path relative to the repo,
        # and docker needs an absolute one to see a host directory.
        config_dir = materialize(
            (Path(session.create_tmp()) / combo).resolve(), optional
        )
        docker_env: list[str] = []
        if "037_snmp.alloy" in optional:
            # 037's top-level local.file components need the device + auth
            # files present even to `validate`. Empty stubs are enough: an
            # empty device list is 0 targets (healthy-idle) and `auths: {}`
            # merges cleanly over the built-in snmp.yml. Both files live inside
            # the single /etc/alloy mount, so point SECRETS_DIR there too.
            write_snmp_fixtures(config_dir, config_dir, devices=[], auths={})
            docker_env = ["-e", "RU_3OPS_DISCOVERY_SECRETS_DIR=/etc/alloy"]
        unformatted = [
            cfg.name
            for cfg in sorted(config_dir.glob("*.alloy"))
            if _alloy_fmt_would_change(config_dir, cfg.name)
        ]
        if unformatted:
            session.error(
                f"[{combo}] alloy fmt would change: " + ", ".join(unformatted)
            )
        session.run(
            "docker",
            "run",
            "--rm",
            *docker_env,
            "-v",
            alloy_config_mount(config_dir),
            ALLOY_IMAGE,
            "validate",
            "--stability.level=experimental",
            "/etc/alloy",
            external=True,
        )
        session.log(f"[{combo}] fmt + validate OK")


@nox.session
def tests(session: nox.Session) -> None:
    """Run the fast docker-free suite (static consistency + app units)."""
    _uv(session, "pytest", "tests/static", "tests/app", *session.posargs)


@nox.session
def e2e(session: nox.Session) -> None:
    """
    Delivery checks against the docker compose stack (opt-in).

    Needs Docker and several minutes: ~20 services, database
    healthchecks, the mini-app image build, and a metrics budget of
    RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL + 30s scrape + flush.
    """
    _uv(session, "pytest", "tests/e2e", "-o", "timeout=900", *session.posargs)


@nox.session
def preflight(session: nox.Session) -> None:
    """Queue every gate except interactive ones."""
    for name in ("lint", "docs_lint", "alloy_check", "tests", "e2e"):
        session.notify(name)


@nox.session
def release(session: nox.Session) -> None:
    """
    Pack the contract and the reference config into dist/.

    Deliberately outside preflight: it writes artifacts rather than
    checking anything. The gates that keep the archive honest (version,
    file set, reproducibility) live in tests/static/test_release.py and
    run as part of ``tests``.
    """
    from tools.release import build, spec_version

    archive = build(REPO / "dist")
    session.log(f"spec version {spec_version()}")
    session.log(f"{archive.name} ({archive.stat().st_size} bytes)")
    session.log(f"checksum in {archive.parent / 'SHA256SUMS'}")


COMPOSE_FILE = REPO / "tests" / "e2e" / "stack" / "docker-compose.yml"


def _materialize_demo(dest: Path) -> Path:
    """Materialize base + every optional file + snmp for the demo."""
    from tools.materialize import COMBOS, materialize

    if dest.exists():
        shutil.rmtree(dest)
    return materialize(dest, COMBOS["all-snmp"])


@nox.session
def demo(session: nox.Session) -> None:
    """
    Interactive demo sandbox: full stack + Grafana (manual, not a gate).

    `uv run nox -s demo`         build + up -d --wait, print URLs, follow logs
    `uv run nox -s demo -- down`  tear the sandbox down (down -v)

    Not queued by preflight: interactive. Grafana opens anonymously with
    Prometheus + Loki pre-wired; the contract's self-metrics give it
    self-monitoring series without extra configuration.
    """
    from tools.snmp_fixtures import write_snmp_fixtures
    from tools.stack_secrets import write_secrets

    if shutil.which("docker") is None:
        session.error("docker is required for the demo sandbox")

    project = "xad-demo"
    compose = (
        "docker",
        "compose",
        "-p",
        project,
        "--profile",
        "demo",
        "-f",
        str(COMPOSE_FILE),
    )
    demo_dir = REPO / ".demo"
    secrets_dir = demo_dir / "secrets"
    snmp_dir = demo_dir / "snmp"

    # Provision the snmp device file BEFORE the env dict: write_snmp_fixtures
    # writes an empty auth here, then write_secrets in the env spread below
    # overwrites snmp_auths.yaml with the real netmon-v3 creds (Task 8). The
    # snmp-agent compose service is unprofiled, so it runs in the demo too.
    write_snmp_fixtures(
        snmp_dir,
        secrets_dir,
        devices=[
            {
                "name": "snmp-agent",
                "address": "snmp-agent:161",
                "module": "if_mib",
                "auth": "netmon-v3",
                "environment": "demo",
                "team": "platform",
            }
        ],
        auths={},
    )

    # `docker compose down` still interpolates the file, so the mandatory
    # ${...:?} vars must be present even for teardown (conftest passes env to
    # every compose call, including down). write_secrets is idempotent and
    # cheap; build the env before branching so `down` gets it too.
    env = {
        **os.environ,
        "RU_3OPS_DISCOVERY_E2E_CONFIG_DIR": str(demo_dir / "config"),
        "RU_3OPS_DISCOVERY_E2E_SECRETS_DIR": str(secrets_dir),
        "RU_3OPS_DISCOVERY_E2E_SNMP_DIR": str(snmp_dir),
        **write_secrets(secrets_dir),
    }
    if session.posargs == ["down"]:
        session.run(*compose, "down", "-v", external=True, env=env)
        return

    _materialize_demo(demo_dir / "config")
    session.run(
        *compose, "up", "--build", "-d", "--wait", external=True, env=env
    )
    for service, port in (
        ("grafana", 3000),
        ("alloy", 12345),
        ("prometheus", 9090),
        ("loki", 3100),
    ):
        out = subprocess.run(
            [*compose, "port", service, str(port)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if out:
            session.log(f"{service:12} http://{out}")
    session.log("Ctrl+C detaches (stack keeps running).")
    session.log("Stop it with: uv run nox -s demo -- down")
    session.run(*compose, "logs", "-f", external=True, env=env)
