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


def _module_is_marked(tree: ast.Module) -> bool:
    """Whether the module sets ``pytestmark`` with the marker."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark"
            for t in node.targets
        ):
            return any(_is_marker(n) for n in ast.walk(node.value))
    return False


def _function_is_marked(node: ast.FunctionDef) -> bool:
    """Whether a function carries the marker as a decorator."""
    return any(
        _is_marker(n) for d in node.decorator_list for n in ast.walk(d)
    )


def _reads_alloy(
    func: ast.FunctionDef,
    functions: dict[str, ast.FunctionDef],
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


def _unmarked_readers() -> tuple[list[str], int]:
    """Return unmarked ``file::test`` readers and the count of readers."""
    readers = _alloy_reader_names()
    unmarked: list[str] = []
    found = 0
    for path in sorted(E2E.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        module_marked = _module_is_marked(tree)
        functions = {
            n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)
        }
        for name, func in functions.items():
            if not name.startswith("test_"):
                continue
            if not _reads_alloy(func, functions, readers):
                continue
            found += 1
            if not (module_marked or _function_is_marked(func)):
                unmarked.append(f"{path.name}::{name}")
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
    assert not unmarked, (
        f"tests reading Alloy internals lack @pytest.mark.{MARKER}: "
        f"{unmarked}"
    )


def test_marker_is_registered() -> None:
    """Pins: --strict-markers rejects an unregistered marker at collection."""
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    markers = config["tool"]["pytest"]["ini_options"].get("markers", [])
    assert any(m.split(":")[0].strip() == MARKER for m in markers)
