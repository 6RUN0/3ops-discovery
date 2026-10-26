"""The host label comes from RU_3OPS_DISCOVERY_HOSTNAME (manifest 6.1)."""

import subprocess

from tests.e2e.conftest import (
    E2E_HOSTNAME,
    LOGS_BUDGET,
    METRICS_BUDGET,
    Stack,
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


def test_host_falls_back_to_the_collector_hostname(snmp_stack: Stack) -> None:
    # The stack leaves the parameter empty: coalesce skips the empty
    # string and lands on the collector hostname.
    container = snmp_stack.compose_container("alloy")
    expected = subprocess.run(
        ["docker", "inspect", "-f", "{{.Config.Hostname}}", container],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert expected
    series = wait_until(
        lambda: snmp_stack.prom_query('sysUpTime{job="snmp"}'),
        timeout=METRICS_BUDGET,
        desc="sysUpTime{job=snmp} delivered",
    )
    assert series[0]["metric"]["host"] == expected
