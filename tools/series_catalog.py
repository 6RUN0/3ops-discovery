"""
The normative series catalog (manifest 14.3): loader, probes, comparison.

One YAML file per domain in ``docs/series/`` names, per cell, the series
every implementation of that domain must emit and the identity labels each
of them must carry; database cells also name the series their profile
switches off. Only names are pinned, never values, and series beyond the
catalog are allowed: it is a lower bound.

``python -m tools.series_catalog snapshot`` dumps what a running stack
actually serves for every probe, as raw material for curating the files.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml

SERIES_DIR = Path(__file__).resolve().parents[1] / "docs" / "series"

#: The only domain whose profiles switch collectors off (manifest 8.4), so
#: the only one where a series can be required to be missing.
_ABSENT_DOMAIN = "database"
_CELL_KEYS = frozenset({"identity", "present", "absent"})
_REQUIRED_CELL_KEYS = frozenset({"identity", "present"})
#: Prometheus metric and label name grammar; also keeps cell_expr's regex
#: alternation free of metacharacters.
_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_QUERY_TIMEOUT_S = 10


class CatalogError(ValueError):
    """A catalog file does not follow the schema."""


@dataclass(frozen=True)
class Cell:
    """One catalog cell: a domain profile or module and its series."""

    domain: str
    name: str
    identity: frozenset[str]
    present: frozenset[str]
    absent: frozenset[str]


@dataclass(frozen=True)
class Probe:
    """
    Where the e2e stack serves a cell's series.

    ``fixture`` names the e2e fixture that runs the emitting containers
    (``stack`` or ``snmp_stack``); ``selector`` is PromQL matchers without
    braces; ``scoped`` adds ``compose_project``, which only series of
    docker-discovered containers carry.
    """

    fixture: str
    selector: str
    scoped: bool


def _blackbox(module: str) -> Probe:
    return Probe("stack", f'job="blackbox",module="{module}"', True)


def _snmp(module: str) -> Probe:
    return Probe("snmp_stack", f'job="snmp",module="{module}"', False)


def _database(job: str, service: str) -> Probe:
    return Probe("stack", f'job="{job}",compose_service="{service}"', True)


#: One probe per catalog cell; test_series_catalog.py demands equality of
#: the key sets. Host-domain job values are the exporter literals the
#: reference stamps (manifest 6.1).
STACK_PROBES: dict[tuple[str, str], Probe] = {
    ("metrics", "scrape"): Probe("stack", 'job="app-metrics"', True),
    ("database", "postgres/basic-v1"): _database("postgres", "postgres-basic"),
    ("database", "postgres/extended-v1"): _database("postgres", "postgres"),
    ("database", "mariadb/standard-v1"): _database("mariadb", "mariadb"),
    ("database", "redis/standard-v1"): _database("redis", "redis"),
    ("database", "mongodb/standard-v1"): _database("mongodb", "mongodb"),
    ("blackbox", "http_2xx"): _blackbox("http_2xx"),
    ("blackbox", "tcp_connect"): _blackbox("tcp_connect"),
    ("blackbox", "icmp"): _blackbox("icmp"),
    ("blackbox", "tls_connect"): _blackbox("tls_connect"),
    ("snmp", "if_mib"): _snmp("if_mib"),
    ("snmp", "system"): _snmp("system"),
    ("host-metrics", "node"): Probe("stack", 'job="integrations/unix"', False),
    ("container-metrics", "cadvisor"): Probe(
        "stack", 'job="integrations/cadvisor"', True
    ),
}


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects a mapping key given twice."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode
) -> dict[Any, Any]:
    keys = [loader.construct_object(key) for key, _ in node.value]
    duplicates = sorted({str(k) for k in keys if keys.count(k) > 1})
    if duplicates:
        raise CatalogError(f"duplicate keys {duplicates} at {node.start_mark}")
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _names(where: str, key: str, value: Any) -> frozenset[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and _NAME.match(item) for item in value
    ):
        raise CatalogError(
            f"{where}: {key} must be a list of series/label names"
        )
    if len(set(value)) != len(value):
        raise CatalogError(f"{where}: {key} lists a name twice")
    return frozenset(value)


def _cell(domain: str, name: Any, body: Any) -> Cell:
    where = f"{domain}/{name}"
    if not isinstance(name, str) or not isinstance(body, dict):
        raise CatalogError(f"{where}: a cell is a name mapped to a mapping")
    unknown = set(body) - _CELL_KEYS
    if unknown:
        raise CatalogError(
            f"{where}: unknown keys {sorted(map(str, unknown))}"
        )
    missing = _REQUIRED_CELL_KEYS - set(body)
    if missing:
        raise CatalogError(f"{where}: missing keys {sorted(missing)}")
    if "absent" in body and domain != _ABSENT_DOMAIN:
        raise CatalogError(
            f"{where}: absent is allowed only in the {_ABSENT_DOMAIN} domain"
        )
    identity = _names(where, "identity", body["identity"])
    present = _names(where, "present", body["present"])
    absent = _names(where, "absent", body.get("absent", []))
    if not identity or not present:
        raise CatalogError(f"{where}: identity and present must not be empty")
    overlap = present & absent
    if overlap:
        raise CatalogError(
            f"{where}: both present and absent: {sorted(overlap)}"
        )
    return Cell(domain, name, identity, present, absent)


def load_catalog(directory: Path = SERIES_DIR) -> dict[tuple[str, str], Cell]:
    """Load every ``<domain>.yaml`` in ``directory`` by (domain, cell)."""
    catalog: dict[tuple[str, str], Cell] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.load(
                path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader
            )
        except yaml.YAMLError as exc:
            raise CatalogError(f"{path.name}: {exc}") from exc
        if not isinstance(data, dict) or set(data) != {"domain", "cells"}:
            raise CatalogError(
                f"{path.name}: top level must be domain + cells"
            )
        if data["domain"] != path.stem:
            raise CatalogError(
                f"{path.name}: domain {data['domain']!r} is not the file name"
            )
        cells = data["cells"]
        if not isinstance(cells, dict) or not cells:
            raise CatalogError(
                f"{path.name}: cells must be a non-empty mapping"
            )
        for name, body in cells.items():
            cell = _cell(path.stem, name, body)
            catalog[cell.domain, cell.name] = cell
    return catalog


def _selector(probe: Probe, project: str) -> str:
    if probe.scoped:
        return f'{probe.selector}, compose_project="{project}"'
    return probe.selector


def cell_expr(cell: Cell, probe: Probe, project: str) -> str:
    """Return one PromQL selector matching every series the cell names."""
    names = "|".join(sorted(cell.present | cell.absent))
    return f'{{__name__=~"^(?:{names})$", {_selector(probe, project)}}}'


def label_names_by_series(
    result: Sequence[Mapping[str, Any]],
) -> dict[str, frozenset[str]]:
    """
    Map each series name to the label names ALL of its series carry.

    Intersection, not union: a label that only some series of a name carry
    (a histogram ``le``, a per-mode ``mode``) is no identity for the name.
    """
    names: dict[str, frozenset[str]] = {}
    for item in result:
        metric = dict(item["metric"])
        name = metric.pop("__name__")
        labels = frozenset(metric)
        names[name] = names[name] & labels if name in names else labels
    return names


def parity_problems(
    cell: Cell, observed: Mapping[str, frozenset[str]]
) -> list[str]:
    """
    Compare what a stack serves for a cell against the cell.

    ``absent`` is checked only once every ``present`` series is found: a
    selector that matches too little would otherwise prove absence for the
    wrong reason.
    """
    where = f"{cell.domain}/{cell.name}"
    problems: list[str] = []
    missing = sorted(cell.present - set(observed))
    problems.extend(f"{where}: series {name} missing" for name in missing)
    for name in sorted(cell.present & set(observed)):
        lacking = sorted(cell.identity - observed[name])
        if lacking:
            problems.append(
                f"{where}: series {name} lacks labels {lacking}"
                f" (observed {sorted(observed[name])})"
            )
    if not missing:
        problems.extend(
            f"{where}: series {name} must be absent"
            for name in sorted(cell.absent & set(observed))
        )
    return problems


def _query(metrics_url: str, expr: str) -> list[dict[str, Any]]:
    resp = requests.get(
        f"{metrics_url}/api/v1/query",
        params={"query": expr},
        timeout=_QUERY_TIMEOUT_S,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"query {expr!r} failed: {payload}")
    return list(payload["data"]["result"])


def _snapshot(
    metrics_url: str, project: str
) -> dict[str, dict[str, list[str]]]:
    snapshot: dict[str, dict[str, list[str]]] = {}
    for (domain, name), probe in sorted(STACK_PROBES.items()):
        result = _query(metrics_url, f"{{{_selector(probe, project)}}}")
        snapshot[f"{domain}/{name}"] = {
            series: sorted(labels)
            for series, labels in sorted(label_names_by_series(result).items())
        }
    return snapshot


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; ``snapshot`` prints every probe's series as YAML."""
    parser = argparse.ArgumentParser(prog="python -m tools.series_catalog")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser(
        "snapshot", help="print series name -> label names for every probe"
    )
    snapshot.add_argument("--metrics-url", required=True)
    snapshot.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    yaml.safe_dump(
        _snapshot(args.metrics_url.rstrip("/"), args.project),
        sys.stdout,
        sort_keys=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
