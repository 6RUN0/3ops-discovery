"""Backend-neutral log query: LogQL and LogsQL translations, stream parsing."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tools.backends import (
    LogQuery,
    LokiBackend,
    UnscopedQueryError,
    VictoriaLogsBackend,
    check_scope,
    loki_result_to_records,
    parse_stream,
    to_logql,
    to_logsql,
    to_seconds,
    victorialogs_rows_to_records,
)

Q = LogQuery(stream={"service_name": "app-fuzz", "compose_project": "p1"})
R = LogQuery(
    stream={"compose_project": "p1"}, stream_regex={"container": ".*alloy.*"}
)


def test_logql_stream_only() -> None:
    assert to_logql(Q) == '{compose_project="p1",service_name="app-fuzz"}'


def test_logql_contains_and_field() -> None:
    q = replace(Q, contains='"event": "burst"', field_present="trace_id")
    assert to_logql(q) == (
        '{compose_project="p1",service_name="app-fuzz"}'
        ' |= "\\"event\\": \\"burst\\"" | trace_id=~".+"'
    )


def test_logql_stream_regex() -> None:
    assert to_logql(R) == '{compose_project="p1",container=~".*alloy.*"}'


def test_logsql_stream_only() -> None:
    assert to_logsql(Q) == '{compose_project="p1",service_name="app-fuzz"}'


def test_logsql_contains_and_field() -> None:
    q = replace(Q, contains='"event": "burst"', field_present="trace_id")
    assert to_logsql(q) == (
        '{compose_project="p1",service_name="app-fuzz"}'
        ' _msg:*"\\"event\\": \\"burst\\""* trace_id:*'
    )


def test_logsql_stream_regex() -> None:
    assert to_logsql(R) == '{compose_project="p1",container=~".*alloy.*"}'


def test_backslash_and_newline_escaped() -> None:
    q = replace(Q, contains="a\\b\nc")
    assert '"a\\\\b\\nc"' in to_logql(q)
    assert '*"a\\\\b\\nc"*' in to_logsql(q)


def test_emoji_survives_both() -> None:
    q = replace(Q, contains="\U0001f600")
    assert "\U0001f600" in to_logql(q)
    assert "\U0001f600" in to_logsql(q)


def test_overlapping_keys_rejected() -> None:
    with pytest.raises(ValueError, match="both stream and stream_regex"):
        LogQuery(stream={"container": "a"}, stream_regex={"container": "b"})


def test_unscoped_query_rejected() -> None:
    with pytest.raises(UnscopedQueryError):
        check_scope(LogQuery(stream={"service_name": "x"}))


def test_unscoped_allowed_when_declared() -> None:
    check_scope(LogQuery(stream={"source": "journal"}, scoped=False))


def test_parse_stream_with_escapes() -> None:
    assert parse_stream('{a="b",c="d\\"e"}') == {"a": "b", "c": 'd"e'}


def test_parse_empty_stream() -> None:
    assert parse_stream("{}") == {}


def test_seconds_of_duration() -> None:
    assert to_seconds("30m") == 1800.0


def test_victorialogs_rows_to_records() -> None:
    rows = [
        {
            "_time": "2026-10-25T00:00:01.5Z",
            "_msg": "b",
            "_stream": '{compose_project="p1"}',
            "_stream_id": "x",
            "compose_project": "p1",
            "trace_id": "t2",
        },
        {
            "_time": "2026-10-25T00:00:01Z",
            "_msg": "a",
            "_stream": '{compose_project="p1"}',
            "_stream_id": "x",
            "compose_project": "p1",
        },
    ]
    got = victorialogs_rows_to_records(rows)
    assert [(r.ts, r.line) for r in got] == [
        ("1792886401000000000", "a"),
        ("1792886401500000000", "b"),
    ]
    assert got[0].stream == {"compose_project": "p1"}
    assert got[1].fields == {"trace_id": "t2"}


def test_loki_result_to_records_takes_structured_metadata() -> None:
    # Shape returned by grafana/loki:3.6.12 query_range with
    # X-Loki-Response-Encoding-Flags: categorize-labels; the third value
    # element may be absent.
    result = [
        {
            "stream": {"compose_project": "p1"},
            "values": [
                [
                    "2",
                    '{"trace_id":"t1"}',
                    {"structuredMetadata": {"trace_id": "t1"}},
                ],
                ["1", "plain"],
            ],
        }
    ]
    got = loki_result_to_records(result)
    assert [(r.ts, r.line) for r in got] == [
        ("2", '{"trace_id":"t1"}'),
        ("1", "plain"),
    ]
    assert got[0].fields == {"trace_id": "t1"}
    assert got[1].fields == {}
    assert got[0].stream == {"compose_project": "p1"}


@pytest.mark.parametrize("backend", [LokiBackend, VictoriaLogsBackend])
@pytest.mark.parametrize("method", ["records", "entries", "streams"])
def test_backend_refuses_unscoped_query_before_any_request(
    backend: type[LokiBackend] | type[VictoriaLogsBackend], method: str
) -> None:
    # Port 9 (discard) on loopback: a request would fail with a
    # RequestException, so reaching UnscopedQueryError proves the scope
    # check runs first.
    with pytest.raises(UnscopedQueryError):
        getattr(backend("http://127.0.0.1:9"), method)(
            LogQuery(stream={"service_name": "x"})
        )
