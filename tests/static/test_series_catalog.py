"""
The series catalog (manifest 14.3): loader, comparison and coverage.

The catalog is the contract for what series every implementation of a
domain emits. A loader that tolerated a typo would turn a cell into one
that always passes, and a cell without a probe would never be checked,
so both failure modes are pinned here rather than left to the e2e run.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path
from typing import Any

import pytest
import requests

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md
from tests.static.asymmetries import SERIES_CELLS_UNCATALOGUED
from tools import series_catalog as sc
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


def _db_profile_ladder() -> list[str]:
    """Database profiles in the 8.4 order, lightest first."""
    ladder = re.search(r"Нагрузка монотонна: ([\w <=]+)\.", md.section("8.4"))
    assert ladder, "8.4 states no profile ordering"
    stems = ladder.group(1).split(" <= ")
    by_stem = {p.rsplit("-v", 1)[0]: p for p in md.db_profiles()}
    assert set(stems) == set(by_stem), (stems, sorted(by_stem))
    return [by_stem[stem] for stem in stems]


def _ladder_problems(catalog: dict[tuple[str, str], Cell]) -> list[str]:
    """Series a heavier database cell lacks from a lighter one of its type."""
    ladder = _db_profile_ladder()
    cells: dict[str, dict[int, Cell]] = {}
    for (domain, name), cell in catalog.items():
        if domain == "database":
            db_type, profile = name.split("/")
            cells.setdefault(db_type, {})[ladder.index(profile)] = cell
    problems = []
    for by_rank in cells.values():
        ranks = sorted(by_rank)
        for low, high in itertools.pairwise(ranks):
            missing = by_rank[low].present - by_rank[high].present
            if missing:
                problems.append(
                    f"{by_rank[high].name} lacks {sorted(missing)}"
                    f" of {by_rank[low].name}"
                )
    return problems


def test_heavier_database_profile_keeps_lighter_series() -> None:
    """
    Pins 8.4 "basic <= standard <= extended" in the catalog cells.

    The catalog is a lower bound for every implementation, so an
    extended-v1 cell missing a series basic-v1 lists let a second
    implementation drop it on extended-v1 and still pass series parity.
    Only catalogued neighbours are compared: a missing middle cell
    leaves the two outer ones adjacent.
    """
    assert _ladder_problems(load_catalog()) == []


def test_ladder_gate_catches_a_series_lost_upward() -> None:
    """The ladder gate fails when a heavier cell drops a lighter series."""
    catalog = {
        ("database", "postgres/basic-v1"): _cell(present={"a", "b"}),
        ("database", "postgres/extended-v1"): Cell(
            domain="database",
            name="postgres/extended-v1",
            identity=frozenset({"job"}),
            present=frozenset({"a", "c"}),
            absent=frozenset(),
        ),
    }
    assert _ladder_problems(catalog) == [
        "postgres/extended-v1 lacks ['b'] of postgres/basic-v1"
    ]


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


# --- Mutation-hardening: probes, exact messages, CLI plumbing ---


def test_probe_helpers_build_the_expected_probe() -> None:
    # The helpers run once at import to fill STACK_PROBES, so the table
    # cannot show a changed helper to a mutation run; call them here. They
    # also fix what the e2e run queries, which this pins without Docker.
    assert sc._blackbox("icmp") == Probe(
        "stack", 'job="blackbox",module="icmp"', True
    )
    assert sc._snmp("if_mib") == Probe(
        "snmp_stack", 'job="snmp",module="if_mib"', False
    )
    assert sc._database("postgres", "postgres-basic") == Probe(
        "stack", 'job="postgres",compose_service="postgres-basic"', True
    )
    assert STACK_PROBES["blackbox", "icmp"] == sc._blackbox("icmp")
    assert STACK_PROBES["snmp", "if_mib"] == sc._snmp("if_mib")
    assert STACK_PROBES["database", "postgres/basic-v1"] == sc._database(
        "postgres", "postgres-basic"
    )


_OK = "    identity: [job]\n    present: [up]\n"


@pytest.mark.parametrize(
    ("domain", "body", "message"),
    [
        (
            "metrics",
            "1:\n" + _OK,
            "metrics/1: a cell is a name mapped to a mapping",
        ),
        (
            "metrics",
            "scrape: [up]\n",
            "metrics/scrape: a cell is a name mapped to a mapping",
        ),
        (
            "metrics",
            "scrape:\n    identity: [job]\n",
            "metrics/scrape: missing keys ['present']",
        ),
        (
            "metrics",
            "scrape:\n" + _OK + "    presnt: [up]\n",
            "metrics/scrape: unknown keys ['presnt']",
        ),
        (
            "metrics",
            "scrape:\n    identity: job\n    present: [up]\n",
            "metrics/scrape: identity must be a list of series/label names",
        ),
        (
            "metrics",
            "scrape:\n    identity: [job]\n    present: [1]\n",
            "metrics/scrape: present must be a list of series/label names",
        ),
        (
            "metrics",
            "scrape:\n    identity: [job]\n    present: [a b]\n",
            "metrics/scrape: present must be a list of series/label names",
        ),
        (
            "metrics",
            "scrape:\n    identity: [job, job]\n    present: [up]\n",
            "metrics/scrape: identity lists a name twice",
        ),
        (
            "database",
            "p/b:\n" + _OK + "    absent: [x, x]\n",
            "database/p/b: absent lists a name twice",
        ),
        (
            "metrics",
            "scrape:\n    identity: []\n    present: [up]\n",
            "metrics/scrape: identity and present must not be empty",
        ),
        (
            "metrics",
            "scrape:\n" + _OK + "    absent: [down]\n",
            "metrics/scrape: absent is allowed only in the database domain",
        ),
        (
            "database",
            "p/b:\n" + _OK + "    absent: [up]\n",
            "database/p/b: both present and absent: ['up']",
        ),
    ],
)
def test_cell_errors_name_the_cell_and_the_defect(
    tmp_path: Path, domain: str, body: str, message: str
) -> None:
    indented = "".join(f"  {line}\n" for line in body.splitlines())
    _write(tmp_path, domain, f"domain: {domain}\ncells:\n{indented}")
    with pytest.raises(CatalogError) as caught:
        load_catalog(tmp_path)
    assert str(caught.value) == message


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- a\n", "metrics.yaml: top level must be domain + cells"),
        (
            "domain: metrics\ncells: {a: {}}\nextra: 1\n",
            "metrics.yaml: top level must be domain + cells",
        ),
        (
            "domain: database\ncells: {a: {}}\n",
            "metrics.yaml: domain 'database' is not the file name",
        ),
        (
            "domain: metrics\ncells: {}\n",
            "metrics.yaml: cells must be a non-empty mapping",
        ),
        (
            "domain: metrics\ncells: [a]\n",
            "metrics.yaml: cells must be a non-empty mapping",
        ),
    ],
)
def test_file_errors_name_the_file_and_the_defect(
    tmp_path: Path, text: str, message: str
) -> None:
    _write(tmp_path, "metrics", text)
    with pytest.raises(CatalogError) as caught:
        load_catalog(tmp_path)
    assert str(caught.value) == message


def test_yaml_syntax_error_names_the_file(tmp_path: Path) -> None:
    _write(tmp_path, "metrics", "domain: [\n")
    with pytest.raises(CatalogError, match=r"^metrics\.yaml: "):
        load_catalog(tmp_path)


def test_duplicate_key_error_names_the_key(tmp_path: Path) -> None:
    _write(
        tmp_path, "metrics", "domain: metrics\ndomain: metrics\ncells: {}\n"
    )
    with pytest.raises(
        CatalogError, match=r"^duplicate keys \['domain'\] at "
    ):
        load_catalog(tmp_path)


def test_parity_messages_are_exact() -> None:
    cell = _cell(present={"a", "b"}, absent={"z"}, identity={"job"})
    where = "database/postgres/basic-v1"
    assert parity_problems(cell, {"b": frozenset()}) == [
        f"{where}: series a missing",
        f"{where}: series b lacks labels ['job'] (observed [])",
    ]
    found = {"a": frozenset({"job"}), "b": frozenset({"job"})}
    assert parity_problems(cell, {**found, "z": frozenset()}) == [
        f"{where}: series z must be absent"
    ]


def test_series_of_a_problem_without_a_series_is_empty() -> None:
    assert sc._series_of("not a parity problem") == ""
    assert sc._series_of("x/y: series pg_up missing") == "pg_up"


def test_label_names_intersect_over_every_series_not_only_the_last() -> None:
    result = [
        {"metric": {"__name__": "a", "job": "x", "mode": "1"}},
        {"metric": {"__name__": "a", "job": "x"}},
        {"metric": {"__name__": "a", "job": "x", "mode": "2"}},
    ]
    assert label_names_by_series(result) == {"a": frozenset({"job"})}


class _Reply:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise requests.HTTPError(f"status {self.status}")

    def json(self) -> dict[str, Any]:
        return self.payload


def test_query_asks_the_instant_query_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def get(url: str, *, params: Any, timeout: Any) -> _Reply:
        calls.append({"url": url, "params": params, "timeout": timeout})
        return _Reply({"status": "success", "data": {"result": [{"m": 1}]}})

    monkeypatch.setattr("tools.series_catalog.requests.get", get)
    assert sc._query("http://m:9", "up") == [{"m": 1}]
    (call,) = calls
    assert call["url"] == "http://m:9/api/v1/query"
    assert call["params"] == {"query": "up"}
    assert call["timeout"] is not None


def test_query_failures_are_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = iter(
        [_Reply({}, status=500), _Reply({"status": "error", "error": "bad"})]
    )
    monkeypatch.setattr(
        "tools.series_catalog.requests.get",
        lambda *_a, **_k: next(replies),
    )
    with pytest.raises(requests.HTTPError):
        sc._query("http://m:9", "up")
    with pytest.raises(RuntimeError, match=r"^query 'up' failed: .*'bad'"):
        sc._query("http://m:9", "up")


def test_snapshot_probes_every_cell_and_sorts_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[str, str]] = []

    def query(url: str, expr: str) -> list[dict[str, Any]]:
        asked.append((url, expr))
        return [{"metric": {"__name__": "up", "job": "x", "instance": "i"}}]

    monkeypatch.setattr(sc, "_query", query)
    snapshot = sc._snapshot("http://m:9", "p1")
    ordered = sorted(STACK_PROBES.items())
    assert list(snapshot) == [f"{d}/{n}" for (d, n), _ in ordered]
    assert all(s == {"up": ["instance", "job"]} for s in snapshot.values())
    assert asked == [
        ("http://m:9", "{" + sc._selector(p, "p1") + "}") for _, p in ordered
    ]
    assert 'compose_project="p1"' in asked[0][1]


def test_main_prints_the_snapshot_as_yaml(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[str, str]] = []

    def snapshot(url: str, project: str) -> dict[str, dict[str, list[str]]]:
        seen.append((url, project))
        return {"z/last": {"b": ["y", "x"]}, "a/first": {"c": []}}

    monkeypatch.setattr(sc, "_snapshot", snapshot)
    code = sc.main(
        ["snapshot", "--metrics-url", "http://m:9/", "--project", "p1"]
    )
    assert code == 0
    assert seen == [("http://m:9", "p1")]
    out = capsys.readouterr().out
    assert out == "z/last:\n  b:\n  - y\n  - x\na/first:\n  c: []\n"


@pytest.mark.parametrize(
    ("argv", "missing"),
    [
        ([], "command"),
        (["snapshot", "--project", "p"], "--metrics-url"),
        (["snapshot", "--metrics-url", "http://m"], "--project"),
    ],
)
def test_main_requires_the_command_and_both_options(
    argv: list[str], missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        sc.main(argv)
    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert "usage: python -m tools.series_catalog" in err
    assert f"required: {missing}" in err


def test_main_help_describes_the_snapshot_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        sc.main(["--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert re.search(
        r"\n\s+snapshot\s+print series name -> label names for every probe\n",
        out,
    ), out
