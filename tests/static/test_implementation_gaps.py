"""
Asymmetry rows of a second implementation stay inside its registry row.

A gap row names (implementation, domain, ...). A row for a domain the
manifest 14 registry does not assign to that implementation excuses
nothing real, and a parity check that hard-codes the implementation
name reads the reference's rows on every collector.
"""

import ast
import re
from pathlib import Path

from tests.static import manifest_doc as md
from tests.static import vmagent_config as vc
from tests.static.asymmetries import (
    DISCOVERY_META_LABELS_ABSENT,
    LOGS_IMPLEMENTATION_GAPS,
    SERIES_PARITY_GAPS,
)

_PARITY_TEST = (
    Path(__file__).resolve().parents[1] / "e2e" / "test_series_parity.py"
)
_IMPLEMENTATION_ARG = 3
_IMPLEMENTATION_CONFIGS = {"vmagent": vc.SCRAPE_CONFIG}


def _implementation_args(source: str) -> list[ast.expr]:
    """
    Return the implementation argument of every unexcused_problems call.

    Both the fourth positional argument and the `implementation=` keyword
    count, so moving the argument to a keyword does not hide it.
    """
    found: list[ast.expr] = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "unexcused_problems"
        ):
            continue
        if len(node.args) > _IMPLEMENTATION_ARG:
            found.append(node.args[_IMPLEMENTATION_ARG])
        found.extend(
            kw.value for kw in node.keywords if kw.arg == "implementation"
        )
    return found


def _is_stack_collector_call(arg: ast.expr) -> bool:
    """Return whether `arg` is `stack.collector(...)`."""
    return (
        isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Attribute)
        and arg.func.attr == "collector"
        and isinstance(arg.func.value, ast.Name)
        and arg.func.value.id == "stack"
    )


def _not_from_the_stack(source: str) -> list[str]:
    """Return the implementation arguments that are not stack.collector()."""
    return [
        ast.unparse(arg)
        for arg in _implementation_args(source)
        if not _is_stack_collector_call(arg)
    ]


def test_parity_takes_the_implementation_from_the_stack() -> None:
    """
    Pins: series parity filters gaps by the cell's own collector.

    A literal "alloy" judged vmagent cells against the reference's rows,
    so a vmagent row could never excuse anything. Only a direct
    stack.collector(...) call passes: a name could be bound to a literal.
    """
    source = _PARITY_TEST.read_text(encoding="utf-8")
    assert _implementation_args(source), (
        "test_series_parity.py calls unexcused_problems nowhere"
    )
    assert _not_from_the_stack(source) == []


def test_finder_flags_a_positional_literal() -> None:
    source = 'unexcused_problems(cell, seen, GAPS, "alloy")\n'
    assert _not_from_the_stack(source) == ["'alloy'"]


def test_finder_flags_a_keyword_literal() -> None:
    source = 'unexcused_problems(cell, seen, GAPS, implementation="alloy")\n'
    assert _not_from_the_stack(source) == ["'alloy'"]


def test_finder_flags_a_name_bound_to_a_literal() -> None:
    source = 'impl = "alloy"\nunexcused_problems(cell, seen, GAPS, impl)\n'
    assert _not_from_the_stack(source) == ["impl"]


def test_finder_accepts_the_stack_collector_in_both_forms() -> None:
    source = (
        "unexcused_problems(cell, seen, GAPS, stack.collector(cell.domain))\n"
        "unexcused_problems(\n"
        "    cell, seen, GAPS, implementation=stack.collector(cell.domain)\n"
        ")\n"
    )
    assert len(_implementation_args(source)) == 2
    assert _not_from_the_stack(source) == []


def test_gap_rows_name_a_domain_of_their_implementation() -> None:
    registry = md.implementations()
    rows = [
        *SERIES_PARITY_GAPS,
        *DISCOVERY_META_LABELS_ABSENT,
        *LOGS_IMPLEMENTATION_GAPS,
    ]
    misplaced = [
        row
        for row in rows
        if row[0] not in registry or row[1] not in registry[row[0]]
    ]
    assert misplaced == []


def test_vmagent_gap_rows_name_the_metrics_domain() -> None:
    rows = [*SERIES_PARITY_GAPS, *DISCOVERY_META_LABELS_ABSENT]
    domains = {row[1] for row in rows if row[0] == "vmagent"}
    assert domains <= {"metrics"}


def test_logs_gap_rows_belong_to_a_non_reference_logs_implementation() -> None:
    """Pins: a logs row names `logs`, an implementation other than alloy."""
    assert LOGS_IMPLEMENTATION_GAPS, "vector rows are the table's reason"
    rows = list(LOGS_IMPLEMENTATION_GAPS)
    assert {row[1] for row in rows} == {"logs"}
    assert {row[0] for row in rows} <= {"vector"}
    assert all(LOGS_IMPLEMENTATION_GAPS[row].strip() for row in rows)


def test_vector_logs_gaps_are_the_registered_ones() -> None:
    topics = {row[2] for row in LOGS_IMPLEMENTATION_GAPS}
    assert len(topics) == len(LOGS_IMPLEMENTATION_GAPS)
    assert {
        "10.3.4 item 4 error metric",
        "10.3.4 item 3 warning rate limit",
        "own container excluded by hostname",
        "lines lost while Vector is down",
        "docker refresh interval not read",
        "logfmt line over 64 KiB",
        "logfmt lone surrogate escape",
    } == topics


def _label_pattern(label: str) -> re.Pattern[str]:
    return re.compile(re.escape(label).replace(re.escape("<name>"), r"\w+"))


def test_absent_discovery_labels_are_unread_by_their_implementation() -> None:
    """A label the implementation never discovers must not drive its rules."""
    read = {
        (impl, label)
        for impl, _domain, label in DISCOVERY_META_LABELS_ABSENT
        if _label_pattern(label).search(
            _IMPLEMENTATION_CONFIGS[impl].read_text(encoding="utf-8")
        )
    }
    assert read == set()


def test_label_pattern_expands_the_name_placeholder() -> None:
    pattern = _label_pattern("__meta_docker_network_label_<name>")
    assert pattern.search("[__meta_docker_network_label_com_example]")
    assert not pattern.search("[__meta_docker_network_ip]")
