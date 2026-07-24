"""
3ops Discovery e2e mini-app.

One image, behaviour via env (manifest 10.3):
    APP_LOG_FORMAT      json | logfmt | raw | mixed | fuzz |
                        python-traceback | java-traceback  (default json)
    APP_METRICS_PORT    serve prometheus_client /metrics on this port
    APP_BURST           "<lines_per_sec>:<seconds>" burst of numbered
                        json lines at startup, then the normal pace
    APP_FUZZ_TELEMETRY  "1": garbage unicode labels + extreme gauge
                        values (counters stay monotonic)
    APP_OTLP_ENDPOINT   OTLP/HTTP base URL (e.g. http://alloy:4318):
                        emit metrics and logs via OTLP instead of stdout

Emission cadence: one log line and one counter increment at least every
EMIT_PERIOD seconds, so e2e timeouts are computable.
"""

from __future__ import annotations

import datetime
import itertools
import json
import logging
import os
import sys
import time
import traceback

from prometheus_client import Counter, Gauge, start_http_server

EMIT_PERIOD = 2.0

EVENTS = Counter("app_events", "Lines emitted by the mini-app")
GAUGE = Gauge("app_gauge", "Oscillating demo gauge")
FUZZ_GAUGE = Gauge(
    "app_fuzz_gauge", "Gauge fuzzed with extreme values", ["variant"]
)

#: Unicode label variants are built from codepoints, not literals, so
#: pre-commit unicode hooks never trip over the source.
FUZZ_VARIANTS = (
    chr(0x1F680) + chr(0x1F600),  # emoji
    chr(0x202E) + "rtl" + chr(0x200D),  # RTL override + ZWJ
    "plain-ascii",
)

#: Extreme-but-finite values; NaN/Inf behaviour is pinned live while the
#: e2e assertions are written.
FUZZ_EXTREMES = (0.0, -1e300, 1e300)


def json_line(seq: int) -> str:
    return json.dumps(
        {
            "event": "tick",
            "level": "info",
            "seq": seq,
            "trace_id": f"trace-{seq}",
            "request_id": f"req-{seq}",
        }
    )


def logfmt_line(seq: int) -> str:
    return (
        f"level=info msg=tick status=200 seq={seq} "
        f"trace_id=trace-{seq} request_id=req-{seq}"
    )


def raw_line(seq: int) -> str:
    return f"plain tick number {seq} without structure"


def text_with_level(seq: int) -> str:
    return f"operator note {seq}: raised level= to high, msg follows"


def mixed_line(seq: int) -> str:
    renderers = (json_line, logfmt_line, raw_line, text_with_level)
    return renderers[seq % len(renderers)](seq)


def parse_burst(value: str) -> tuple[int, float]:
    """Parse APP_BURST "<lines_per_sec>:<seconds>"."""
    rate, _, seconds = value.partition(":")
    return int(rate), float(seconds)


def run_burst(rate: int, seconds: float) -> None:
    """Emit numbered json lines at ~rate/s for the given duration."""
    total = int(rate * seconds)
    started = time.monotonic()
    for seq in range(total):
        print(json.dumps({"event": "burst", "seq": seq}), flush=False)
        if seq % rate == rate - 1:
            sys.stdout.flush()
            # Pace one second's worth of lines per wall-clock second.
            target = started + (seq + 1) / rate
            time.sleep(max(0.0, target - time.monotonic()))
    sys.stdout.flush()
    print(json.dumps({"event": "burst-done", "total": total}), flush=True)


def _stamp(seq: int) -> str:
    # Deterministic monotone-ish timestamp; UTC ISO, no random().
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    ts = base + datetime.timedelta(seconds=seq)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def python_traceback_block(seq: int) -> str:
    """Build a real Python traceback prefixed by one timestamped header."""
    try:
        raise ValueError(f"synthetic failure {seq}")  # noqa: TRY301
    except ValueError:
        tb = traceback.format_exc().rstrip("\n")
    return f"{_stamp(seq)} ERROR request {seq} failed\n{tb}"


def java_traceback_block(seq: int) -> str:
    """Build a canonical Java-style stack trace with a timestamped header."""
    frames = (
        "\tat com.example.Service.handle(Service.java:42)\n"
        "\tat com.example.Server.dispatch(Server.java:17)\n"
        "\tat java.base/java.lang.Thread.run(Thread.java:840)"
    )
    return (
        f'{_stamp(seq)} ERROR Exception in thread "main" '
        f"java.lang.IllegalStateException: synthetic {seq}\n{frames}"
    )


def emit(fmt: str, seq: int) -> None:
    if fmt == "fuzz":
        for payload in fuzz_payloads(seq):
            sys.stdout.buffer.write(payload + b"\n")
        sys.stdout.buffer.flush()
        return
    if fmt == "python-traceback":
        print(python_traceback_block(seq), flush=True)
        return
    if fmt == "java-traceback":
        print(java_traceback_block(seq), flush=True)
        return
    renderers = {
        "json": json_line,
        "logfmt": logfmt_line,
        "raw": raw_line,
        "mixed": mixed_line,
    }
    print(renderers[fmt](seq), flush=True)


def fuzz_telemetry_tick(seq: int) -> None:
    variant = FUZZ_VARIANTS[seq % len(FUZZ_VARIANTS)]
    FUZZ_GAUGE.labels(variant=variant).set(
        FUZZ_EXTREMES[seq % len(FUZZ_EXTREMES)]
    )


FUZZ_MARKER_EVERY = 5


def _fuzz_corpus(seq: int) -> list[bytes]:
    """
    Programmatically built garbage.

    Escapes and codepoints, never literals, so pre-commit unicode hooks
    and the gates themselves do not trip over the test data.
    """
    emoji = (chr(0x1F600) + chr(0x1F469) + chr(0x200D) + chr(0x1F4BB)).encode()
    rtl = (chr(0x202E) + "reversed" + chr(0x202C)).encode()
    ansi = b"\x1b[31mred\x1b[0m plain tail"
    control = b"ctl:\x01\x02\x03 nul:\x00 end"
    invalid_utf8 = b"broken \xff\xfe\xfa bytes"
    # Big enough to exercise a huge line, but under Loki's default
    # max_line_size (262144 bytes) so it is ingested rather than rejected
    # -- the reference config does not truncate (manifest 6.2), so an
    # over-limit line would be dropped by Loki and is out of scope here.
    huge = b"x" * 230_000
    broken_json = b'{"level": "info", "unterminated": '
    corpus = [emoji, rtl, ansi, control, invalid_utf8, huge, broken_json]
    # Vary the order per seq without random(): deterministic replay.
    offset = seq % len(corpus)
    return corpus[offset:] + corpus[:offset]


def fuzz_payloads(seq: int) -> list[bytes]:
    """Garbage payloads plus a valid json marker every Nth second."""
    payloads = _fuzz_corpus(seq)
    if seq and seq % FUZZ_MARKER_EVERY == 0:
        marker = json.dumps({"event": "fuzz-marker", "marker": seq})
        payloads.append(marker.encode())
    return payloads


def otlp_resource_attributes(seq: int, *, fuzz: bool) -> dict[str, str]:
    """
    Build the resource attributes for the OTLP path.

    service.name is the only allowlist-promoted attribute (060_otel hint).
    Fuzz mode adds extra attributes with unicode values built from
    codepoints (never literals) to prove the allowlist keeps them out of
    labels, not merely that valid data flows.
    """
    attrs = {"service.name": "app-otel"}
    if fuzz:
        attrs["fuzz.unicode"] = FUZZ_VARIANTS[seq % len(FUZZ_VARIANTS)]
        attrs["fuzz.seq"] = str(seq)
    return attrs


def run_otlp(endpoint: str, *, fuzz: bool) -> None:
    """Emit OTLP metrics and logs to the collector endpoint, forever."""
    from opentelemetry import metrics as otel_metrics
    from opentelemetry._logs import get_logger_provider, set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import (
        OTLPLogExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create(otlp_resource_attributes(0, fuzz=fuzz))
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics")
    )
    otel_metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[reader])
    )
    counter = otel_metrics.get_meter("app").create_counter("app_otlp_events")

    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=f"{endpoint}/v1/logs")
        )
    )
    set_logger_provider(provider)
    handler = LoggingHandler(logger_provider=get_logger_provider())
    otlp_log = logging.getLogger("app.otlp")
    otlp_log.addHandler(handler)
    otlp_log.setLevel(logging.INFO)

    for seq in itertools.count():
        counter.add(1)
        otlp_log.info("otlp tick %d", seq)
        time.sleep(EMIT_PERIOD)


def main() -> int:
    fmt = os.environ.get("APP_LOG_FORMAT", "json")
    metrics_port = os.environ.get("APP_METRICS_PORT")
    fuzz_telemetry = os.environ.get("APP_FUZZ_TELEMETRY") == "1"
    burst = os.environ.get("APP_BURST")

    otlp_endpoint = os.environ.get("APP_OTLP_ENDPOINT")
    if otlp_endpoint:
        run_otlp(otlp_endpoint, fuzz=fuzz_telemetry)
        return 0  # run_otlp loops forever

    if metrics_port:
        start_http_server(int(metrics_port))
    if burst:
        run_burst(*parse_burst(burst))

    for seq in itertools.count():
        emit(fmt, seq)
        EVENTS.inc()
        GAUGE.set(seq % 60)
        if fuzz_telemetry:
            fuzz_telemetry_tick(seq)
        time.sleep(EMIT_PERIOD)
    return 0  # pragma: no cover - itertools.count never ends


if __name__ == "__main__":
    raise SystemExit(main())
