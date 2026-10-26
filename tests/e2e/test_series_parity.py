"""Series parity: the reference delivers every cell of the series catalog."""

import dataclasses

import pytest

from tests.e2e.conftest import (
    METRICS_BUDGET,
    ReadinessTimeoutError,
    Stack,
    wait_until,
)
from tests.static.asymmetries import SERIES_PARITY_GAPS
from tools.series_catalog import (
    STACK_PROBES,
    cell_expr,
    label_names_by_series,
    load_catalog,
    unexcused_problems,
)

_CATALOG = load_catalog()


def _observed(stack: Stack, expr: str) -> dict[str, frozenset[str]]:
    return label_names_by_series(stack.prom_query(expr))


@pytest.mark.parametrize("cell_key", sorted(_CATALOG), ids="/".join)
def test_reference_delivers_the_catalogue(
    cell_key: tuple[str, str], request: pytest.FixtureRequest
) -> None:
    cell = _CATALOG[cell_key]
    probe = STACK_PROBES[cell_key]
    stack: Stack = request.getfixturevalue(probe.fixture)
    expr = cell_expr(cell, probe, stack.project)
    # Absent series are judged only after the poll: accepting them early
    # could not tell "not emitted" from "not yet scraped".
    present_only = dataclasses.replace(cell, absent=frozenset())
    last_problems: list[str] = ["no read completed"]
    satisfying: list[dict[str, frozenset[str]]] = []

    def all_present() -> bool:
        observed = _observed(stack, expr)
        last_problems[:] = unexcused_problems(
            present_only, observed, SERIES_PARITY_GAPS, "alloy"
        )
        if not last_problems:
            satisfying[:] = [observed]
        return not last_problems

    try:
        wait_until(
            all_present,
            timeout=METRICS_BUDGET,
            desc=f"series catalog cell {'/'.join(cell_key)} delivered",
        )
    except ReadinessTimeoutError as exc:
        pytest.fail(f"{exc}; last problems: {last_problems}")
    # Judge the observation that satisfied the poll: two series of one scrape
    # can be missing from consecutive instant queries, so a fresh read could
    # report a present series missing.
    problems = unexcused_problems(
        cell, satisfying[0], SERIES_PARITY_GAPS, "alloy"
    )
    assert problems == []
