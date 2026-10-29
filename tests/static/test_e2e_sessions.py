"""One list of e2e sessions: preflight and the e2e.yml matrix follow it."""

import ast
from pathlib import Path

import noxfile as nx
import yaml

NOXFILE = Path(nx.__file__)


class _NotifyRecorder:
    """Records the sessions a nox session body queues, without running them."""

    def __init__(self) -> None:
        self.notified: list[str] = []

    def notify(self, name: str) -> None:
        self.notified.append(name)


def _is_nox_session(func: ast.FunctionDef) -> bool:
    return any(
        ast.unparse(d).startswith("nox.session") for d in func.decorator_list
    )


def _calls_run_e2e(func: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_run_e2e"
        for node in ast.walk(func)
    )


def test_every_e2e_session_is_listed() -> None:
    """Pins the list: an e2e session outside it escapes preflight."""
    tree = ast.parse(NOXFILE.read_text(encoding="utf-8"))
    sessions = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and _is_nox_session(node)
        and _calls_run_e2e(node)
    }
    assert sessions == set(nx.E2E_SESSIONS)


def test_preflight_queues_every_e2e_session() -> None:
    """Pins the spec rule: the whole e2e matrix runs in preflight."""
    recorder = _NotifyRecorder()
    nx.preflight(recorder)
    missing = set(nx.E2E_SESSIONS) - set(recorder.notified)
    assert missing == set()


def test_e2e_workflow_matrix_is_the_session_list() -> None:
    """Pins CI to the list: a cell missing in e2e.yml never runs."""
    doc = yaml.safe_load(
        (nx.WORKFLOWS_DIR / "e2e.yml").read_text(encoding="utf-8")
    )
    matrix = doc["jobs"]["e2e"]["strategy"]["matrix"]["session"]
    assert matrix == list(nx.E2E_SESSIONS)
