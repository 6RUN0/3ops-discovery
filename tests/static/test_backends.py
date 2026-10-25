"""Backend-neutral log query: LogQL and LogsQL translations, stream parsing."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tools.backends import (
    LogQuery,
    UnscopedQueryError,
    check_scope,
    parse_stream,
    to_logql,
    to_logsql,
    to_seconds,
)

Q = LogQuery(stream={"service_name": "app-fuzz", "compose_project": "p1"})
R = LogQuery(stream={"compose_project": "p1"}, stream_regex={"container": ".*alloy.*"})


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
    assert "\U0001f600" in to_logql(q) and "\U0001f600" in to_logsql(q)


def test_overlapping_keys_rejected() -> None:
    with pytest.raises(ValueError):
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


def test_to_seconds() -> None:
    assert to_seconds("30m") == 1800.0
