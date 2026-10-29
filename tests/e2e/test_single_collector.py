"""
One collector per domain on a host (manifest 14).

Two collectors of one domain produce series and streams that differ only
in `collector` or `host`; a store cannot tell them from real data. The
checks run on every e2e cell: a split deployment (vmagent, Vector, Alloy)
must not collect a target twice, and neither must the reference alone.
host-metrics, otel and host-logs stay out: their data carries no
compose_project, and each has one implementation in the registry.
"""

from typing import Any

from tests.e2e.conftest import (
    LOGS_BUDGET,
    METRICS_BUDGET,
    PROJECT_DOMAIN_PROBES,
    Stack,
    project_selector,
    wait_until,
)
from tools.backends import LogQuery, duplicate_groups

#: Scrape interval of the default profile (manifest 8.2).
_SCRAPE_INTERVAL = 30.0


def _wait_for_project_series(stack: Stack) -> None:
    """
    Block until every probed domain has data and three scrapes happened.

    Three scrapes of app-metrics leave a minute after the first: a second
    collector that discovers the target within that minute has delivered,
    so a `-k` run right after bring-up does not pass before a duplicate
    exists. Logs checks reuse the wait: it outlasts a log collector's start.
    """
    for domain, expr in PROJECT_DOMAIN_PROBES.items():
        query = project_selector(stack.project, expr)

        def probe(query: str = query) -> list[dict[str, Any]]:
            return stack.prom_query(query)

        wait_until(
            probe,
            timeout=METRICS_BUDGET,
            desc=f"{domain} series in the project",
        )
    up = project_selector(stack.project, 'up{job="app-metrics"}')
    wait_until(
        lambda: stack.prom_query(f"count_over_time({up}[5m]) >= 3"),
        timeout=METRICS_BUDGET + 2 * _SCRAPE_INTERVAL,
        desc="three scrapes of app-metrics",
    )


def _describe(groups: list[list[dict[str, str]]], name: str) -> str:
    """Name each duplicate group by `name` and its collector/host pairs."""
    described = []
    for group in groups:
        pairs = {(s.get("collector"), s.get("host")) for s in group}
        # key=repr: a pair with a missing label holds None, which a plain
        # sort cannot compare with a string.
        described.append(f"{group[0].get(name)} by {sorted(pairs, key=repr)}")
    return "; ".join(described)


def test_no_series_is_collected_twice(stack: Stack) -> None:
    _wait_for_project_series(stack)
    series = stack.prom_query(f'{{compose_project="{stack.project}"}}')
    duplicates = duplicate_groups(s["metric"] for s in series)
    assert duplicates == [], "series collected twice: " + _describe(
        duplicates, "__name__"
    )


def test_no_target_is_scraped_by_two_collectors(stack: Stack) -> None:
    """
    Catch a double scrape whose labels differ beyond collector and host.

    Manifest 14 names duplicates that differ only in collector or host; a
    second collector that adds or rewrites a label other than job, instance
    and compose_service slips past that rule, so targets are compared by
    those three alone.
    """
    _wait_for_project_series(stack)
    target = "job, instance, compose_service"
    up = f'up{{compose_project="{stack.project}"}}'
    doubled = stack.prom_query(
        f"count by ({target}) (count by ({target}, collector) ({up})) > 1"
    )
    assert doubled == [], [s["metric"] for s in doubled]


def test_no_stream_is_collected_twice(stack: Stack) -> None:
    _wait_for_project_series(stack)
    wait_until(
        lambda: stack.log_streams(
            LogQuery(
                stream={
                    "compose_service": "app-logs-raw",
                    "compose_project": stack.project,
                }
            )
        ),
        timeout=LOGS_BUDGET,
        desc="app-logs-raw stream",
    )
    streams = stack.log_streams(
        LogQuery(stream={"compose_project": stack.project})
    )
    duplicates = duplicate_groups(streams)
    assert duplicates == [], "streams collected twice: " + _describe(
        duplicates, "compose_service"
    )
    assert {s.get("collector") for s in streams} == {stack.collector("logs")}
