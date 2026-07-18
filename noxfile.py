"""
Nox sessions for the X-Alloy Discovery quality gates.

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


def _alloy_fmt_would_change(config_dir: Path, name: str) -> bool:
    """
    Return True if ``alloy fmt`` would reformat the named file.

    Uses ``fmt -t`` (non-mutating): the image exits non-zero when the
    file is not already in canonical format, so nothing is written back.
    """
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{config_dir}:/etc/alloy:ro",
            ALLOY_IMAGE,
            "fmt",
            "-t",
            f"/etc/alloy/{name}",
        ],
        capture_output=True,
        check=False,
    )
    return result.returncode != 0


@nox.session
def alloy_check(session: nox.Session) -> None:
    """
    Fmt (non-mutating -t) + validate for every directory combination.

    Combinations come from tools.materialize.COMBOS; each is
    materialized into a temp dir and mounted as one read-only volume,
    exercising the same overlay mechanism the e2e stack uses.
    """
    from tools.materialize import COMBOS, materialize

    if shutil.which("docker") is None:
        session.error("docker is required for alloy_check")
    for combo, optional in COMBOS.items():
        config_dir = materialize(Path(session.create_tmp()) / combo, optional)
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
            "-v",
            f"{config_dir}:/etc/alloy:ro",
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
    XAD_DOCKER_REFRESH_INTERVAL + 30s scrape + flush.
    """
    _uv(
        session, "pytest", "tests/e2e", "-o", "timeout=900", *session.posargs
    )


@nox.session
def preflight(session: nox.Session) -> None:
    """Queue every gate except interactive ones."""
    for name in ("lint", "docs_lint", "alloy_check", "tests", "e2e"):
        session.notify(name)
