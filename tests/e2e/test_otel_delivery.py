"""OTLP receiver delivery (manifest 5.1, 6.2 label discipline)."""

from tests.e2e.conftest import (
    LOGS_BUDGET,
    METRICS_BUDGET,
    Stack,
    wait_until,
)
from tests.static import manifest_doc as md


def test_otlp_metrics_reach_prometheus(stack: Stack) -> None:
    # The counter is created via the OTLP path only; its presence proves
    # otelcol.receiver.otlp -> exporter.prometheus -> remote_write works.
    wait_until(
        lambda: (
            stack.prom_query("app_otlp_events_total")
            or stack.prom_query("app_otlp_events")
        ),
        timeout=METRICS_BUDGET,
        desc="otlp counter present in prometheus",
    )


def test_otlp_logs_reach_loki_only_via_otlp(stack: Stack) -> None:
    # app-otel sets logs.enabled=false, so the docker path is off; any
    # entry proves the OTLP logs path.
    wait_until(
        lambda: (
            stack.loki_entries(
                # The OTLP path produces no provenance (manifest 10.5),
                # so an OTLP stream has no compose_project to scope by --
                # and both stacks run an app-otel of the same name.
                '{service_name="app-otel"}',
                since="30m",
                scoped=False,
            )
            or None
        ),
        timeout=LOGS_BUDGET + 30,
        desc="otlp log entries in loki",
    )


def test_otlp_stream_labels_within_allowlist(stack: Stack) -> None:
    streams = wait_until(
        lambda: (
            stack.loki_series('{service_name="app-otel"}', scoped=False)
            or None
        ),
        timeout=LOGS_BUDGET + 30,
        desc="app-otel stream present",
    )
    allowlist = md.loki_label_allowlist()
    for labels in streams:
        # Loki injects internal book-keeping labels (__*); manifest 6.2
        # governs contract stream labels only, so ignore the __* ones.
        contract = {n for n in labels if not n.startswith("__")}
        extra = contract - allowlist
        assert not extra, f"otel stream carries non-allowlist labels: {extra}"
