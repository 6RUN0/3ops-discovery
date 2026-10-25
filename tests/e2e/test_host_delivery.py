"""Host telemetry delivery (manifest 14.5): node_* metrics, journal logs."""

import uuid

from tests.e2e.conftest import (
    JOURNAL_HOST,
    LOGS_BUDGET,
    METRICS_BUDGET,
    Stack,
    wait_until,
)
from tools.backends import LogQuery


def test_node_metrics_delivered(stack: Stack) -> None:
    # 070_host-metrics runs prometheus.exporter.unix inside alloy; the
    # series reflect the runner host. node_uname_info is one stable series
    # per host. Ephemeral Prometheus receives only from this stack, so an
    # unscoped presence check is sound (no compose_project on host series:
    # the exporter target has no docker discovery metadata).
    series = wait_until(
        lambda: stack.prom_query("node_uname_info"),
        timeout=METRICS_BUDGET,
        desc="node_uname_info present",
    )
    # 070 attaches manifest 6.1 provenance via discovery.relabel: node_*
    # series must be attributable to their collector in a multi-host
    # installation.
    labels = series[0]["metric"]
    assert labels["collector"] == "alloy"
    assert labels["host"]


def test_journal_logs_delivered(stack: Stack) -> None:
    """
    Pin 080_host-logs end to end: a journal entry reaches the log store.

    Defect pinned: on a host without a persistent journal (CI runners,
    this dev host) 080 had no end-to-end proof at all. journal-host
    supplies the journal, so the check never skips; a marker unique to
    this run proves delivery of this entry, not of older journal content.
    """
    marker = f"xad-e2e-journal-{uuid.uuid4().hex}"
    written = stack.compose_exec(
        JOURNAL_HOST, "logger", "-t", "xad-e2e", marker
    )
    assert written.returncode == 0, written.stderr
    # Journal streams come from the host, not from a container, so they
    # carry no compose labels to scope by (manifest 14.5); the marker is
    # what limits the query to this run.
    records = wait_until(
        lambda: stack.log_records(
            LogQuery(
                stream={"source": "journal"}, contains=marker, scoped=False
            )
        ),
        timeout=LOGS_BUDGET,
        desc="journal marker in the log store",
    )
    # format_as_json = false: the stored line is the MESSAGE field alone.
    assert [r.line for r in records] == [marker]
    labels = records[0].stream
    assert labels["collector"] == "alloy"
    assert labels["source"] == "journal"
    assert labels["host"]
