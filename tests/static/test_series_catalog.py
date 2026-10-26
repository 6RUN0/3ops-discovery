"""
The series catalog (manifest 14.3): loader, comparison and coverage.

The catalog is the contract for what series every implementation of a
domain emits. A loader that tolerated a typo would turn a cell into one
that always passes, and a cell without a probe would never be checked,
so both failure modes are pinned here rather than left to the e2e run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md
from tests.static.asymmetries import SERIES_CELLS_UNCATALOGUED
from tools.series_catalog import (
    STACK_PROBES,
    CatalogError,
    Cell,
    Probe,
    cell_expr,
    label_names_by_series,
    load_catalog,
    parity_problems,
)

_PROVENANCE = {"job", "instance", "host", "collector"}


def _write(directory: Path, domain: str, body: str) -> Path:
    path = directory / f"{domain}.yaml"
    path.write_text(body, encoding="utf-8")
    return directory


def _cell(**kwargs: set[str]) -> Cell:
    return Cell(
        domain="database",
        name="postgres/basic-v1",
        identity=frozenset(kwargs.get("identity", {"job"})),
        present=frozenset(kwargs.get("present", {"a"})),
        absent=frozenset(kwargs.get("absent", set())),
    )


# --- Loader ---


def test_valid_file_loads(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "database",
        "domain: database\n"
        "cells:\n"
        "  postgres/basic-v1:\n"
        "    identity: [job, instance]\n"
        "    present: [pg_up]\n"
        "    absent: [pg_stat_statements_calls_total]\n",
    )
    catalog = load_catalog(tmp_path)
    assert catalog == {
        ("database", "postgres/basic-v1"): Cell(
            domain="database",
            name="postgres/basic-v1",
            identity=frozenset({"job", "instance"}),
            present=frozenset({"pg_up"}),
            absent=frozenset({"pg_stat_statements_calls_total"}),
        )
    }


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    # A typo would otherwise leave a cell with no required series, which
    # passes every parity check.
    _write(
        tmp_path,
        "metrics",
        "domain: metrics\n"
        "cells:\n"
        "  scrape:\n"
        "    identity: [job]\n"
        "    presnt: [up]\n",
    )
    with pytest.raises(CatalogError, match="presnt"):
        load_catalog(tmp_path)


def test_empty_present_is_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "metrics",
        "domain: metrics\ncells:\n  scrape:\n    identity: [job]\n"
        "    present: []\n",
    )
    with pytest.raises(CatalogError, match="present"):
        load_catalog(tmp_path)


def test_absent_outside_database_is_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "metrics",
        "domain: metrics\ncells:\n  scrape:\n    identity: [job]\n"
        "    present: [up]\n    absent: [down]\n",
    )
    with pytest.raises(CatalogError, match="absent"):
        load_catalog(tmp_path)


def test_present_and_absent_overlap_is_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "database",
        "domain: database\ncells:\n  postgres/basic-v1:\n"
        "    identity: [job]\n    present: [pg_up]\n    absent: [pg_up]\n",
    )
    with pytest.raises(CatalogError, match="pg_up"):
        load_catalog(tmp_path)


def test_domain_must_match_file_name(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "metrics",
        "domain: database\ncells:\n  scrape:\n    identity: [job]\n"
        "    present: [up]\n",
    )
    with pytest.raises(CatalogError, match="domain"):
        load_catalog(tmp_path)


def test_duplicate_cell_is_rejected(tmp_path: Path) -> None:
    # safe_load keeps the last of two equal keys, silently dropping the
    # first cell's series.
    _write(
        tmp_path,
        "metrics",
        "domain: metrics\ncells:\n"
        "  scrape:\n    identity: [job]\n    present: [up]\n"
        "  scrape:\n    identity: [job]\n    present: [scrape_series_added]\n",
    )
    with pytest.raises(CatalogError, match="duplicate"):
        load_catalog(tmp_path)


# --- Comparison ---


def test_parity_reports_missing_series_label_and_unexpected_absent() -> None:
    cell = _cell(present={"a", "b"}, absent={"z"}, identity={"job"})
    problems = parity_problems(
        cell,
        {"a": frozenset({"job"}), "b": frozenset(), "z": frozenset({"job"})},
    )
    assert len(problems) == 2, problems
    assert any("b" in p and "job" in p for p in problems), problems
    assert any("z" in p and "absent" in p for p in problems), problems


def test_parity_defers_absent_until_every_present_series_is_found() -> None:
    # A selector that matches too little would make "z is absent" true for
    # the wrong reason; while a required series is missing, the absent
    # check proves nothing and is not reported.
    cell = _cell(present={"a", "b"}, absent={"z"}, identity={"job"})
    problems = parity_problems(
        cell, {"b": frozenset({"job"}), "z": frozenset({"job"})}
    )
    assert len(problems) == 1, problems
    assert "a" in problems[0]
    assert "missing" in problems[0]


def test_parity_ignores_extra_series_and_labels() -> None:
    # The catalog is a lower bound (manifest 14.3).
    cell = _cell(present={"a"}, identity={"job"})
    observed = {"a": frozenset({"job", "extra"}), "other": frozenset()}
    assert parity_problems(cell, observed) == []


def test_label_names_are_intersected_across_series_of_one_name() -> None:
    result = [
        {"metric": {"__name__": "a", "job": "x", "instance": "1", "le": "1"}},
        {"metric": {"__name__": "a", "job": "x", "instance": "2"}},
        {"metric": {"__name__": "b", "job": "x"}},
    ]
    assert label_names_by_series(result) == {
        "a": frozenset({"job", "instance"}),
        "b": frozenset({"job"}),
    }


def test_cell_expr_scopes_only_when_asked() -> None:
    cell = _cell(present={"b", "a"}, absent={"z"})
    scoped = cell_expr(cell, Probe("stack", 'job="postgres"', True), "p1")
    unscoped = cell_expr(cell, Probe("stack", 'job="postgres"', False), "p1")
    assert scoped == (
        '{__name__=~"^(?:a|b|z)$", job="postgres", compose_project="p1"}'
    )
    assert unscoped == '{__name__=~"^(?:a|b|z)$", job="postgres"}'


# --- Catalog against the manifest and the reference config ---


def test_catalogued_domains_match_the_identity_table() -> None:
    assert {c.domain for c in load_catalog().values()} == set(
        md.series_identity()
    )


def test_identity_holds_job_instance_and_provenance() -> None:
    table = md.series_identity()
    for cell in load_catalog().values():
        extra = set(
            re.findall(r"`([^`]+)`", table[cell.domain]["Дополнительно"])
        )
        missing = (_PROVENANCE | extra) - cell.identity
        assert not missing, (
            f"{cell.domain}/{cell.name} identity lacks {missing}"
        )


def test_database_cells_are_catalogued_or_declared_gaps() -> None:
    expected = {f"{t}/{p}" for t in md.db_types() for p in md.db_profiles()}
    catalogued = {
        name for domain, name in load_catalog() if domain == "database"
    }
    declared = {
        name
        for domain, name in SERIES_CELLS_UNCATALOGUED
        if domain == "database"
    }
    assert not catalogued & declared, catalogued & declared
    assert catalogued | declared == expected


def test_blackbox_cells_cover_shipped_modules() -> None:
    cells = {name for domain, name in load_catalog() if domain == "blackbox"}
    assert cells == ac.blackbox_config_modules()


def test_snmp_cells_cover_shipped_modules() -> None:
    cells = {name for domain, name in load_catalog() if domain == "snmp"}
    assert cells == ac.snmp_relabel_modules()


def test_every_cell_has_a_probe_and_back() -> None:
    # A cell without a probe is never checked; a probe without a cell
    # checks nothing.
    assert set(load_catalog()) == set(STACK_PROBES)


def test_no_phantom_gaps() -> None:
    real = {
        ("database", f"{t}/{p}")
        for t in md.db_types()
        for p in md.db_profiles()
    }
    assert set(SERIES_CELLS_UNCATALOGUED) <= real
