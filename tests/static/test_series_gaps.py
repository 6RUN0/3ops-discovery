"""The series gap filter hides exactly the series a gap row names."""

from tools.series_catalog import Cell, unexcused_problems


def _cell() -> Cell:
    return Cell(
        domain="database",
        name="postgres/extended-v1",
        identity=frozenset({"job"}),
        present=frozenset({"up", "pg_a", "pg_b"}),
        absent=frozenset({"pg_off"}),
    )


def _gap(series: str) -> dict[tuple[str, str, str, str], str]:
    return {("alloy", "database", "postgres/extended-v1", series): "test"}


_OBSERVED = {
    "up": frozenset({"job"}),
    "pg_b": frozenset(),
    "pg_off": frozenset({"job"}),
}


def test_all_three_problem_formats_are_reported_without_gaps() -> None:
    problems = unexcused_problems(_cell(), _OBSERVED, {}, "alloy")
    # absent (pg_off) is not judged while pg_a is missing
    assert len(problems) == 2
    assert "series pg_a missing" in problems[0]
    assert "series pg_b lacks labels" in problems[1]
    both = dict(_OBSERVED, pg_a=frozenset({"job"}))
    problems = unexcused_problems(_cell(), both, {}, "alloy")
    assert len(problems) == 2
    assert "series pg_b lacks labels" in problems[0]
    assert "series pg_off must be absent" in problems[1]


def test_gap_hides_missing_series_only() -> None:
    problems = unexcused_problems(_cell(), _OBSERVED, _gap("pg_a"), "alloy")
    assert all("pg_a" not in p for p in problems)
    assert any("pg_b" in p for p in problems)


def test_gap_hides_lacking_labels_and_absent_series() -> None:
    both = dict(_OBSERVED, pg_a=frozenset({"job"}))
    gaps = {**_gap("pg_b"), **_gap("pg_off")}
    assert unexcused_problems(_cell(), both, gaps, "alloy") == []
    only_b = unexcused_problems(_cell(), both, _gap("pg_b"), "alloy")
    assert len(only_b) == 1
    assert "pg_off" in only_b[0]


def test_gap_of_another_implementation_or_cell_hides_nothing() -> None:
    other = {("other", "database", "postgres/extended-v1", "pg_a"): "x"}
    other |= {("alloy", "database", "mariadb/standard-v1", "pg_a"): "x"}
    assert unexcused_problems(_cell(), _OBSERVED, other, "alloy") == (
        unexcused_problems(_cell(), _OBSERVED, {}, "alloy")
    )
