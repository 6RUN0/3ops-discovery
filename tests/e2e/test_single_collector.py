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

from tests.e2e.conftest import LOGS_BUDGET, METRICS_BUDGET, Stack, wait_until
from tools.backends import LogQuery, duplicate_groups

#: One series per domain with targets in the stack, read inside the same
#: compose_project scope the duplicate check compares (ipmi has no target).
_DOMAIN_PROBES = {
    "metrics": 'up{job="app-metrics"}',
    "database": "pg_up",
    "blackbox": "probe_success",
    "container-metrics": "container_cpu_usage_seconds_total",
}
#: Scrape interval of the default profile (manifest 8.2).
_SCRAPE_INTERVAL = 30.0


def _scoped(stack: Stack, expr: str) -> str:
    """Add the compose_project matcher to a selector with or without one."""
    scope = f'compose_project="{stack.project}"'
    if expr.endswith("}"):
        return expr[:-1] + f",{scope}}}"
    return f"{expr}{{{scope}}}"


def _wait_for_project_series(stack: Stack) -> None:
    """
    Block until every probed domain has data and two scrapes happened.

    By the second scrape of app-metrics any second collector with the same
    interval has scraped at least once, so a `-k` run right after bring-up
    cannot pass before a duplicate exists.
    """
    for domain, expr in _DOMAIN_PROBES.items():
        query = _scoped(stack, expr)

        def probe(query: str = query) -> list[dict[str, Any]]:
            return stack.prom_query(query)

        wait_until(
            probe,
            timeout=METRICS_BUDGET,
            desc=f"{domain} series in the project",
        )
    up = _scoped(stack, 'up{job="app-metrics"}')
    wait_until(
        lambda: stack.prom_query(f"count_over_time({up}[5m]) >= 2"),
        timeout=METRICS_BUDGET + _SCRAPE_INTERVAL,
        desc="two scrapes of app-metrics",
    )


def test_no_series_is_collected_twice(stack: Stack) -> None:
    _wait_for_project_series(stack)
    series = stack.prom_query(f'{{compose_project="{stack.project}"}}')
    duplicates = duplicate_groups(s["metric"] for s in series)
    assert duplicates == [], "series collected twice: " + "; ".join(
        f"{group[0].get('__name__')} by "
        f"{sorted({(s.get('collector'), s.get('host')) for s in group})}"
        for group in duplicates
    )


def test_no_target_is_scraped_by_two_collectors(stack: Stack) -> None:
    """
    Catch a double scrape whose labels differ beyond collector and host.

    Manifest 14 names duplicates that differ only in collector or host; a
    second collector that adds or rewrites a label would slip past that
    rule, so targets are compared by job, instance and service alone.
    """
    _wait_for_project_series(stack)
    target = "job, instance, compose_service"
    up = f'up{{compose_project="{stack.project}"}}'
    doubled = stack.prom_query(
        f"count by ({target}) "
        f"(count by ({target}, collector) ({up})) > 1"
    )
    assert doubled == [], [s["metric"] for s in doubled]


def test_no_stream_is_collected_twice(stack: Stack) -> None:
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
    assert duplicate_groups(streams) == []
    assert {s["collector"] for s in streams} == {stack.collector("logs")}
