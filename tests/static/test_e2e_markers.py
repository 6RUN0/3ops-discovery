"""Structural gate: e2e tests that read Alloy internals carry a marker."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
E2E = REPO / "tests" / "e2e"
MARKER = "alloy_internals"


def _alloy_reader_names() -> set[str]:
    """
    Attribute names that reach Alloy internals through ``Stack``.

    The ``alloy_url`` attribute plus every ``Stack`` method whose body
    uses a reader through ``self``, transitively. Derived from the AST so
    a new helper is covered without editing this gate.
    """
    tree = ast.parse((E2E / "conftest.py").read_text())
    stack = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "Stack"
    )
    methods = {n.name: n for n in stack.body if isinstance(n, ast.FunctionDef)}
    readers = {"alloy_url"}
    changed = True
    while changed:
        changed = False
        for name, node in methods.items():
            if name in readers:
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Attribute)
                    and isinstance(sub.value, ast.Name)
                    and sub.value.id == "self"
                    and sub.attr in readers
                ):
                    readers.add(name)
                    changed = True
                    break
    return readers


def _is_marker(node: ast.AST) -> bool:
    """Whether an expression is ``pytest.mark.alloy_internals``."""
    return isinstance(node, ast.Attribute) and node.attr == MARKER


def _assigns_marker(body: list[ast.stmt]) -> bool:
    """Whether a module or class body sets ``pytestmark`` with the marker."""
    for node in body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets
        ):
            return any(_is_marker(n) for n in ast.walk(value))
    return False


def _is_marked_by_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> bool:
    """Whether a function or class carries the marker as a decorator."""
    return any(_is_marker(n) for d in node.decorator_list for n in ast.walk(d))


def _reads_alloy(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    readers: set[str],
) -> bool:
    """
    Whether a function reaches a reader through same-file calls.

    Walking the whole body includes nested functions and lambdas; a name
    that resolves to a module function is followed.
    """
    seen: set[str] = set()
    pending = [func]
    while pending:
        current = pending.pop()
        for node in ast.walk(current):
            if isinstance(node, ast.Attribute) and node.attr in readers:
                return True
            if (
                isinstance(node, ast.Name)
                and node.id in functions
                and node.id not in seen
            ):
                seen.add(node.id)
                pending.append(functions[node.id])
    return False


def _unmarked_in(tree: ast.Module, readers: set[str]) -> tuple[list[str], int]:
    """
    Return unmarked reader tests of one module and the count of readers.

    Covers ``def`` and ``async def`` tests at module level and as methods
    of a class; a marker may sit on the test, on its class, or in a
    ``pytestmark`` assignment (plain or annotated) of the module or class.
    Names are ``test`` or ``Class::test``.
    """
    functions = {
        n.name: n
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    module_marked = _assigns_marker(tree.body)
    candidates: list[
        tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, bool]
    ] = [(name, func, module_marked) for name, func in functions.items()]
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_marked = (
                module_marked
                or _is_marked_by_decorator(node)
                or _assigns_marker(node.body)
            )
            candidates += [
                (f"{node.name}::{m.name}", m, class_marked)
                for m in node.body
                if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
    unmarked: list[str] = []
    found = 0
    for name, func, marked in candidates:
        if not name.rpartition("::")[2].startswith("test_"):
            continue
        if not _reads_alloy(func, functions, readers):
            continue
        found += 1
        if not (marked or _is_marked_by_decorator(func)):
            unmarked.append(name)
    return unmarked, found


def _unmarked_readers() -> tuple[list[str], int]:
    """Return unmarked ``file::test`` readers and the count of readers."""
    readers = _alloy_reader_names()
    unmarked: list[str] = []
    found = 0
    for path in sorted(E2E.glob("test_*.py")):
        names, count = _unmarked_in(ast.parse(path.read_text()), readers)
        unmarked += [f"{path.name}::{name}" for name in names]
        found += count
    return unmarked, found


def test_every_alloy_ui_reader_is_marked() -> None:
    """
    Pins: a test reading Alloy internals runs in a contract-only selection.

    Other implementations run conformance with ``-m "not alloy_internals"``;
    an unmarked reader would fail there for a reason that is not a
    contract violation.
    """
    unmarked, found = _unmarked_readers()
    assert found > 0, "positive control: no Alloy-reading test found"
    assert "alloy_components" in _alloy_reader_names()
    assert not unmarked, (
        f"tests reading Alloy internals lack @pytest.mark.{MARKER}: {unmarked}"
    )


def test_marker_is_registered() -> None:
    """Pins: --strict-markers rejects an unregistered marker at collection."""
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    markers = config["tool"]["pytest"]["ini_options"].get("markers", [])
    assert any(m.split(":")[0].strip() == MARKER for m in markers)


_SYNTHETIC = """
import pytest
{module_level}

def test_clean(stack):
    return 1

def test_plain(stack):
    stack.alloy_url

@pytest.mark.alloy_internals
def test_marked(stack):
    stack.alloy_url

async def test_async(stack):
    stack.alloy_url

def test_via_helper(stack):
    _helper(stack)

def _helper(stack):
    stack.alloy_components()

class TestGroup:
    def test_method(self, stack):
        stack.alloy_url

    @pytest.mark.alloy_internals
    def test_method_marked(self, stack):
        stack.alloy_url
"""


def _synthetic(module_level: str = "") -> tuple[list[str], int]:
    tree = ast.parse(_SYNTHETIC.format(module_level=module_level))
    return _unmarked_in(tree, {"alloy_url", "alloy_components"})


def test_gate_flags_every_unmarked_shape() -> None:
    """Pins: async tests, class methods and helper calls are not skipped."""
    unmarked, found = _synthetic()
    assert sorted(unmarked) == [
        "TestGroup::test_method",
        "test_async",
        "test_plain",
        "test_via_helper",
    ]
    assert found == 6


def test_gate_honours_module_markers_of_both_assignment_forms() -> None:
    """Pins: an annotated ``pytestmark`` marks the module like a plain one."""
    plain = "pytestmark = pytest.mark.alloy_internals"
    annotated = "pytestmark: object = pytest.mark.alloy_internals"
    assert _synthetic(plain) == ([], 6)
    assert _synthetic(annotated) == ([], 6)
    assert _synthetic("pytestmark = pytest.mark.slow")[0]


def test_gate_honours_class_marker() -> None:
    """Pins: a class decorator marks its methods, not the module's tests."""
    source = _SYNTHETIC.replace(
        "class TestGroup:",
        "@pytest.mark.alloy_internals\nclass TestGroup:",
    ).format(module_level="")
    unmarked, _ = _unmarked_in(ast.parse(source), {"alloy_url"})
    assert "TestGroup::test_method" not in unmarked
    assert "test_plain" in unmarked
