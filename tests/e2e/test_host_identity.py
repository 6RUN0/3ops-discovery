"""The host label comes from RU_3OPS_DISCOVERY_HOSTNAME (manifest 6.1)."""

import subprocess
from typing import Any

from tests.e2e.conftest import (
    E2E_HOSTNAME,
    LOGS_BUDGET,
    METRICS_BUDGET,
    PROJECT_DOMAIN_PROBES,
    Stack,
    project_selector,
    wait_until,
)
from tools.backends import LogQuery


def test_host_comes_from_the_parameter(stack: Stack) -> None:
    series = wait_until(
        lambda: stack.prom_query(
            f'up{{job="app-metrics",compose_project="{stack.project}"}}'
        ),
        timeout=METRICS_BUDGET,
        desc="app-metrics series",
    )
    assert series[0]["metric"]["host"] == E2E_HOSTNAME
    streams = wait_until(
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
    assert {s["host"] for s in streams} == {E2E_HOSTNAME}


def test_every_domain_reports_one_host(stack: Stack) -> None:
    """
    Pins manifest 14: one machine is one `host` across its collectors.

    Each collector of a split deployment reads the same parameter, so
    every domain's series, container logs and the journal agree; the
    per-domain checks only compare each to the value. A missing label
    lands in the set as None and fails the comparison.
    """
    hosts: set[str | None] = set()
    for expr in (
        *(
            project_selector(stack.project, probe)
            for probe in PROJECT_DOMAIN_PROBES.values()
        ),
        f'{{compose_project="{stack.project}"}}',
        "node_uname_info",
        "app_otlp_events_total",
    ):

        def series_of(expr: str = expr) -> list[dict[str, Any]]:
            return stack.prom_query(expr)

        series = wait_until(
            series_of, timeout=METRICS_BUDGET, desc=f"{expr} delivered"
        )
        hosts |= {s["metric"].get("host") for s in series}
    for query in (
        LogQuery(stream={"compose_project": stack.project}),
        LogQuery(stream={"source": "journal"}, scoped=False),
    ):

        def streams_of(query: LogQuery = query) -> list[dict[str, str]]:
            return stack.log_streams(query)

        streams = wait_until(
            streams_of,
            timeout=LOGS_BUDGET,
            desc=f"{dict(query.stream)} streams",
        )
        hosts |= {s.get("host") for s in streams}
    assert hosts == {E2E_HOSTNAME}


def _container_hostname(stack: Stack, service: str) -> str:
    hostname = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            "{{.Config.Hostname}}",
            stack.compose_container(service),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert hostname
    return hostname


def test_host_falls_back_to_the_collector_hostname(snmp_stack: Stack) -> None:
    # The stack leaves the parameter empty: coalesce skips the empty
    # string and lands on the collector hostname.
    expected = _container_hostname(snmp_stack, "alloy")
    series = wait_until(
        lambda: snmp_stack.prom_query('sysUpTime{job="snmp"}'),
        timeout=METRICS_BUDGET,
        desc="sysUpTime{job=snmp} delivered",
    )
    assert series[0]["metric"]["host"] == expected


def test_metrics_host_falls_back_to_its_collector_hostname(
    snmp_stack: Stack,
) -> None:
    # Same empty parameter, metrics domain: the fallback is the hostname of
    # whichever collector runs that domain, vmagent included.
    expected = _container_hostname(snmp_stack, snmp_stack.collector("metrics"))
    series = wait_until(
        lambda: snmp_stack.prom_query(
            f'up{{job="app-metrics",compose_project="{snmp_stack.project}"}}'
        ),
        timeout=METRICS_BUDGET,
        desc="app-metrics series on the snmp stack",
    )
    assert {s["metric"]["host"] for s in series} == {expected}


def test_logs_host_falls_back_to_its_collector_hostname(
    snmp_stack: Stack,
) -> None:
    """Pins 14.1: an empty hostname falls back to the logs collector's own."""
    # Same empty parameter, logs domain: the fallback is the hostname of
    # whichever collector runs that domain, Vector included.
    expected = _container_hostname(snmp_stack, snmp_stack.collector("logs"))
    streams = wait_until(
        lambda: snmp_stack.log_streams(
            LogQuery(
                stream={
                    "compose_service": "app-logs-raw",
                    "compose_project": snmp_stack.project,
                }
            )
        ),
        timeout=LOGS_BUDGET,
        desc="app-logs-raw stream on the snmp stack",
    )
    assert {s["host"] for s in streams} == {expected}
