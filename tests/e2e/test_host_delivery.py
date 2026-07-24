"""Host telemetry delivery (spec 5.4): node_* metrics, journal logs."""

import pytest

from tests.e2e.conftest import (
    LOGS_BUDGET,
    METRICS_BUDGET,
    Stack,
    wait_until,
)


def test_node_metrics_delivered(stack: Stack) -> None:
    # 070_host-metrics runs prometheus.exporter.unix inside alloy; the
    # series reflect the runner host. node_uname_info is one stable series
    # per host. Ephemeral Prometheus receives only from this stack, so an
    # unscoped presence check is sound (no compose_project on host series:
    # the exporter target has no docker discovery metadata).
    wait_until(
        lambda: stack.prom_query("node_uname_info"),
        timeout=METRICS_BUDGET,
        desc="node_uname_info present",
    )


def test_journal_logs_delivered(stack: Stack) -> None:
    if not stack.host_journal:
        pytest.skip("no persistent journal (/var/log/journal) on this host")
    # 080_host-logs streams the systemd journal with static labels
    # host/collector/source. The ephemeral Loki receives only from this
    # stack, so an unscoped selector on source="journal" is sound.
    streams = wait_until(
        lambda: stack.loki_series('{source="journal"}'),
        timeout=LOGS_BUDGET,
        desc="journal streams in Loki",
    )
    labels = streams[0]
    assert labels["collector"] == "alloy"
    assert labels["source"] == "journal"
    assert labels["host"]
