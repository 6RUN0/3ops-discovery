"""Backend-neutral log query: LogQL and LogsQL translations, stream parsing."""

from __future__ import annotations

import ast
import re
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest
import requests

from tests.static import manifest_doc as md
from tools.backends import (
    BACKEND_NAMES,
    LOGS_IMPL_DOMAINS,
    LOGS_IMPLEMENTATIONS,
    METRICS_IMPL_DOMAINS,
    METRICS_IMPLEMENTATIONS,
    REFERENCE_IMPLEMENTATION,
    LogQuery,
    LokiBackend,
    UnscopedQueryError,
    VictoriaLogsBackend,
    _stream_selector,
    check_scope,
    loki_result_to_records,
    parse_json_lines,
    parse_stream,
    selected_backend,
    selected_logs_implementation,
    selected_metrics_implementation,
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


@pytest.mark.parametrize("name", ["", "a b", 'a"b', "a-b", "1a", "a|b", "a}"])
def test_bad_label_names_are_rejected(name: str) -> None:
    # Names are interpolated into the query unquoted, so a stray character
    # would change the query instead of failing.
    with pytest.raises(ValueError, match="label name"):
        LogQuery(stream={name: "v"})
    with pytest.raises(ValueError, match="label name"):
        LogQuery(stream={"compose_project": "p"}, stream_regex={name: "v"})
    with pytest.raises(ValueError, match="label name"):
        LogQuery(stream={"compose_project": "p"}, field_present=name)


def test_empty_contains_is_rejected() -> None:
    # `|= ""` matches every line: the query would pass for any stream.
    with pytest.raises(ValueError, match=r"^contains must not be empty$"):
        LogQuery(stream={"compose_project": "p"}, contains="")


def test_query_is_frozen_but_not_hashable() -> None:
    # Documented in the LogQuery docstring: frozen for immutability, the
    # dict fields make it unhashable.
    with pytest.raises(FrozenInstanceError):
        Q.contains = "x"  # type: ignore[misc]
    with pytest.raises(TypeError, match="unhashable"):
        hash(Q)


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


@pytest.mark.parametrize(
    "duration", ["-5s", "nans", "infs", "1e3s", " 5s", "s"]
)
def test_duration_must_be_a_plain_non_negative_decimal(duration: str) -> None:
    with pytest.raises(ValueError, match="bad duration"):
        to_seconds(duration)


@pytest.mark.parametrize("text", ['{="v"}', '{a b="v"}', '{1a="v"}'])
def test_stream_key_must_be_a_label_name(text: str) -> None:
    message = f"bad label name in stream string: {text!r}"
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        parse_stream(text)


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


def test_victorialogs_live_row_shape() -> None:
    # Trimmed row from victoriametrics/victoria-logs:v1.53.0
    # /select/logsql/query (e2e_victoria run): stream labels repeat as
    # top-level fields, structured metadata from Alloy are plain fields,
    # and `_time` drops trailing zeros (8 fractional digits here).
    rows = parse_json_lines(
        '{"_msg":"{\\"seq\\": 5, \\"trace_id\\": \\"trace-5\\"}",'
        '"_stream":"{compose_project=\\"p1\\",service_name=\\"s\\"}",'
        '"_stream_id":"00e1","_time":"2026-10-25T17:09:49.61550042Z",'
        '"compose_project":"p1","service_name":"s","trace_id":"trace-5"}\n'
    )
    (record,) = victorialogs_rows_to_records(rows)
    assert record.ts == "1792948189615500420"
    assert record.line == '{"seq": 5, "trace_id": "trace-5"}'
    assert record.stream == {"compose_project": "p1", "service_name": "s"}
    assert record.fields == {"trace_id": "trace-5"}


def test_json_lines_skip_blank_lines() -> None:
    assert parse_json_lines('{"a": "1"}\n\n{"b": "2"}') == [
        {"a": "1"},
        {"b": "2"},
    ]


def test_bad_json_line_names_its_position() -> None:
    with pytest.raises(ValueError, match=r"line 2 .*'\{oops'"):
        parse_json_lines('{"a": "1"}\n{oops\n')


@pytest.mark.parametrize("line", ["[1, 2]", '"text"', "7", "null"])
def test_json_line_that_is_not_an_object_names_its_position(line: str) -> None:
    with pytest.raises(ValueError, match=r"line 2 .*not a JSON object"):
        parse_json_lines(f'{{"a": "1"}}\n{line}\n')


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


def test_default_backend() -> None:
    assert selected_backend({}) == "prometheus-loki"


def test_unknown_backend_is_loud() -> None:
    with pytest.raises(ValueError, match="prometheus-loki, victoria"):
        selected_backend({"RU_3OPS_DISCOVERY_E2E_BACKEND": "victoria-metrics"})


def test_default_metrics_implementation() -> None:
    assert METRICS_IMPLEMENTATIONS == ("alloy", "vmagent")
    assert selected_metrics_implementation({}) == "alloy"


def test_vmagent_metrics_implementation_is_accepted() -> None:
    env = {"RU_3OPS_DISCOVERY_E2E_METRICS_IMPL": "vmagent"}
    assert selected_metrics_implementation(env) == "vmagent"


def test_unknown_metrics_implementation_is_loud() -> None:
    with pytest.raises(ValueError, match="alloy, vmagent"):
        selected_metrics_implementation(
            {"RU_3OPS_DISCOVERY_E2E_METRICS_IMPL": "vmagnet"}
        )


def test_default_logs_implementation() -> None:
    assert LOGS_IMPLEMENTATIONS == ("alloy", "vector")
    assert selected_logs_implementation({}) == "alloy"


def test_vector_logs_implementation_is_accepted() -> None:
    env = {"RU_3OPS_DISCOVERY_E2E_LOGS_IMPL": "vector"}
    assert selected_logs_implementation(env) == "vector"


def test_unknown_logs_implementation_is_loud() -> None:
    with pytest.raises(ValueError, match="alloy, vector"):
        selected_logs_implementation(
            {"RU_3OPS_DISCOVERY_E2E_LOGS_IMPL": "vectro"}
        )


def test_axes_are_read_independently() -> None:
    env = {
        "RU_3OPS_DISCOVERY_E2E_METRICS_IMPL": "vmagent",
        "RU_3OPS_DISCOVERY_E2E_LOGS_IMPL": "vector",
    }
    assert selected_metrics_implementation(env) == "vmagent"
    assert selected_logs_implementation(env) == "vector"


def test_unscoped_error_tells_how_to_fix() -> None:
    with pytest.raises(
        UnscopedQueryError,
        match="add 'compose_project' to stream, or pass scoped=False if it "
        "is meant to span the host",
    ):
        check_scope(LogQuery(stream={"service_name": "x"}))


def test_control_characters_are_hex_escaped() -> None:
    q = replace(Q, contains="a\x01b\r\x7f")
    assert '"a\\x01b\\x0d\\x7f"' in to_logql(q)
    assert '*"a\\x01b\\x0d\\x7f"*' in to_logsql(q)


def test_parse_stream_hex_escape_and_spaced_separator() -> None:
    assert parse_stream('{a="\\x41\\x7fb", X="c"}') == {
        "a": "A\x7fb",
        "X": "c",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{a="b"', "not a stream string: '{a=\"b\"'"),
        ("{a=b}", "malformed stream string: '{a=b}'"),
        ('{a="b}', "unterminated value in stream string: '{a=\"b}'"),
        ('{a="\\x41}', "unterminated value in stream string"),
        ('{a="\\qzz"}', "bad escape in stream string: "),
        ('{a="\\x"}', "bad escape in stream string: "),
    ],
)
def test_malformed_stream_strings_are_named(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        parse_stream(text)


@pytest.mark.parametrize(
    "text",
    ['{a="b"x}', '{a="b" c="d"}', '{a="b",}', '{a="b"c="d"}'],
)
def test_stream_with_garbage_between_pairs_is_rejected(text: str) -> None:
    message = f"malformed stream string: {text!r}"
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        parse_stream(text)


@pytest.mark.parametrize(
    "text", ['{a="b" , c="d"}', '{a="b"  ,   c="d"}', '{a="b",c="d" }']
)
def test_spaces_around_the_pair_separator_are_allowed(text: str) -> None:
    assert parse_stream(text) == {"a": "b", "c": "d"}


@pytest.mark.parametrize("text", ['{a="\\u00}', '{a="\\U0001f60}'])
def test_short_hex_escape_at_the_end_is_a_bad_escape(text: str) -> None:
    # Digits that are all valid hex but too few must not decode, nor fall
    # through to the "unterminated" message.
    message = f"bad escape in stream string: {text!r}"
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        parse_stream(text)


def test_bad_unicode_escape_message_quotes_the_whole_text() -> None:
    text = '{a="\\uzzzz"}'
    message = f"bad escape in stream string: {text!r}"
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        parse_stream(text)


@pytest.mark.parametrize(
    ("escaped", "char"),
    [
        ("\\r", "\r"),
        ("\\a", "\a"),
        ("\\b", "\b"),
        ("\\f", "\f"),
        ("\\v", "\v"),
        ("\\u00e9", "\u00e9"),
        ("\\U0001f600", "\U0001f600"),
    ],
)
def test_parse_stream_reads_go_escapes(escaped: str, char: str) -> None:
    assert parse_stream(f'{{a="x{escaped}y"}}') == {"a": f"x{char}y"}


@pytest.mark.parametrize("escaped", ["\\u00", "\\uzzzz", "\\U0011ffff"])
def test_parse_stream_rejects_bad_unicode_escapes(escaped: str) -> None:
    with pytest.raises(ValueError, match="bad escape in stream string"):
        parse_stream(f'{{a="{escaped}"}}')


@pytest.mark.parametrize(
    "value",
    ["plain", 'q"uote', "back\\slash", "a\x01b\r\n\t\x7f", "\U0001f600,}{"],
)
def test_quote_and_parse_stream_round_trip(value: str) -> None:
    # `_quote` is the writer of the same literal syntax parse_stream reads.
    rendered = _stream_selector(LogQuery(stream={"k": value}))
    assert parse_stream(rendered) == {"k": value}


@pytest.mark.parametrize(
    ("duration", "seconds"), [("90s", 90.0), ("30m", 1800.0), ("2h", 7200.0)]
)
def test_seconds_of_each_unit(duration: str, seconds: float) -> None:
    assert to_seconds(duration) == seconds


@pytest.mark.parametrize("duration", ["", "30", "30d", "m", "xs", "1.5.2m"])
def test_bad_durations_raise_value_error(duration: str) -> None:
    # IndexError escapes wait_until and KeyError is retried silently until
    # the budget ends; ValueError must name the bad input.
    with pytest.raises(ValueError, match="duration"):
        to_seconds(duration)


def _ts_of(stamp: str) -> str:
    row = {"_time": stamp, "_msg": "", "_stream": "{}"}
    return victorialogs_rows_to_records([row])[0].ts


def test_nine_fraction_digits_are_kept() -> None:
    assert _ts_of("2026-10-25T00:00:01.123456789Z") == "1792886401123456789"


@pytest.mark.parametrize(
    ("stamp", "message"),
    [
        ("2026-10-25T00:00:01+03:00", "expected a UTC timestamp ending in Z"),
        ("2026-10-25T00:00:01.1234567890Z", "bad fractional seconds in"),
        ("2026-10-25T00:00:01.5aZ", "bad fractional seconds in"),
    ],
)
def test_bad_timestamps_are_named(stamp: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _ts_of(stamp)


@pytest.mark.parametrize("backend", [LokiBackend, VictoriaLogsBackend])
@pytest.mark.parametrize(
    "extra", [{"contains": "x"}, {"field_present": "trace_id"}]
)
def test_streams_refuse_line_filters_before_any_request(
    backend: type[LokiBackend] | type[VictoriaLogsBackend],
    extra: dict[str, str],
) -> None:
    query = replace(Q, **extra)  # type: ignore[arg-type]
    with pytest.raises(
        TypeError,
        match=r"^streams\(\) selects by stream labels only; drop contains",
    ):
        backend("http://127.0.0.1:9").streams(query)


# --- Request shape against a fake HTTP layer ---

_BASE = "http://store:1"
#: Fixed clock for LokiBackend: start/end are derived from time.time_ns().
_NOW_NS = 2_000_000_000_000_000_000


class _FakeResponse:
    """The slice of requests.Response the backends use."""

    def __init__(
        self, *, status: int = 200, text: str = "", payload: Any = None
    ) -> None:
        self.status = status
        self.text = text
        self.payload = payload

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise requests.HTTPError(f"status {self.status}")

    def json(self) -> Any:
        return self.payload


def _fake_http(
    monkeypatch: pytest.MonkeyPatch, *responses: _FakeResponse
) -> list[dict[str, Any]]:
    """Serve `responses` in order; return the recorded calls."""
    calls: list[dict[str, Any]] = []

    def get(
        url: str,
        *,
        params: Any = None,
        headers: Any = None,
        timeout: Any = None,
    ) -> _FakeResponse:
        call = {"url": url, "params": params, "headers": headers}
        calls.append({**call, "timeout": timeout})
        return responses[len(calls) - 1]

    monkeypatch.setattr("tools.backends.requests.get", get)
    monkeypatch.setattr("tools.backends.time.time_ns", lambda: _NOW_NS)
    return calls


def _loki_result(*values: list[Any]) -> _FakeResponse:
    stream = {"stream": {"compose_project": "p1"}, "values": list(values)}
    return _FakeResponse(payload={"data": {"result": [stream]}})


def test_loki_records_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_http(monkeypatch, _loki_result(["10", "b"], ["9", "a"]))
    got = LokiBackend(_BASE).records(Q, since="1m")
    assert [(r.ts, r.line) for r in got] == [("9", "a"), ("10", "b")]
    (call,) = calls
    assert call["url"] == f"{_BASE}/loki/api/v1/query_range"
    assert call["params"] == {
        "query": to_logql(Q),
        "start": str(_NOW_NS - 60 * 10**9),
        "end": str(_NOW_NS),
        "limit": "5000",
        "direction": "forward",
    }
    assert call["headers"] == {
        "X-Loki-Response-Encoding-Flags": "categorize-labels"
    }
    assert call["timeout"] is not None


def test_loki_records_pages_forward(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.backends._LOKI_PAGE", 2)
    calls = _fake_http(
        monkeypatch,
        _loki_result(["10", "c"], ["5", "a"]),
        _loki_result(["7", "b"]),
    )
    got = LokiBackend(_BASE).records(Q, since="1m")
    assert [r.line for r in got] == ["a", "b", "c"]
    assert [c["params"]["start"] for c in calls] == [
        str(_NOW_NS - 60 * 10**9),
        "11",
    ]
    assert calls[1]["params"]["limit"] == "2"


def test_loki_streams_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    labels = {"compose_project": "p1", "service_name": "s"}
    calls = _fake_http(monkeypatch, _FakeResponse(payload={"data": [labels]}))
    assert LokiBackend(_BASE).streams(Q, since="1m") == [labels]
    (call,) = calls
    assert call["url"] == f"{_BASE}/loki/api/v1/series"
    assert call["params"] == {"match[]": to_logql(Q), "since": "1m"}
    assert call["timeout"] is not None


_VL_ROW = (
    '{"_msg":"m","_stream":"{compose_project=\\"p1\\"}",'
    '"_time":"2026-10-25T00:00:01Z","compose_project":"p1","k":"v"}'
)


def test_victorialogs_records_request_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_http(monkeypatch, _FakeResponse(text=_VL_ROW + "\n"))
    (record,) = VictoriaLogsBackend(_BASE).records(Q, since="1m")
    assert (record.line, dict(record.fields)) == ("m", {"k": "v"})
    (call,) = calls
    assert call["url"] == f"{_BASE}/select/logsql/query"
    assert call["params"] == {
        "query": to_logsql(Q),
        "start": "1m",
        "end": "now",
    }
    assert call["timeout"] is not None


def test_victorialogs_streams_request_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"values": [{"value": '{compose_project="p1"}', "hits": 3}]}
    calls = _fake_http(monkeypatch, _FakeResponse(payload=payload))
    got = VictoriaLogsBackend(_BASE).streams(Q, since="1m")
    assert got == [{"compose_project": "p1"}]
    (call,) = calls
    assert call["url"] == f"{_BASE}/select/logsql/streams"
    assert call["params"] == {
        "query": to_logsql(Q),
        "start": "1m",
        "end": "now",
    }
    assert call["timeout"] is not None


@pytest.mark.parametrize(
    ("since", "expected", "window_ns"),
    [(None, "30m", 1800 * 10**9), ("1m", "1m", 60 * 10**9)],
)
def test_entries_pass_the_window_through(
    monkeypatch: pytest.MonkeyPatch,
    since: str | None,
    expected: str,
    window_ns: int,
) -> None:
    window = {} if since is None else {"since": since}
    calls = _fake_http(
        monkeypatch,
        _loki_result(["9", "a"]),
        _FakeResponse(text=_VL_ROW),
    )
    assert LokiBackend(_BASE).entries(Q, **window) == [("9", "a")]
    assert VictoriaLogsBackend(_BASE).entries(Q, **window) == [
        ("1792886401000000000", "m")
    ]
    assert calls[0]["params"]["start"] == str(_NOW_NS - window_ns)
    assert calls[1]["params"]["start"] == expected


def test_entries_is_defined_once_for_both_backends() -> None:
    # Two copies of the one-liner can drift apart; the shared base keeps
    # `entries` a function of `records` alone.
    assert "entries" not in vars(LokiBackend)
    assert "entries" not in vars(VictoriaLogsBackend)
    assert LokiBackend.entries is VictoriaLogsBackend.entries


def test_default_window_is_thirty_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_http(
        monkeypatch,
        _loki_result(["9", "a"]),
        _FakeResponse(payload={"data": []}),
        _FakeResponse(text=_VL_ROW),
        _FakeResponse(payload={"values": []}),
    )
    LokiBackend(_BASE).records(Q)
    LokiBackend(_BASE).streams(Q)
    VictoriaLogsBackend(_BASE).records(Q)
    VictoriaLogsBackend(_BASE).streams(Q)
    assert calls[0]["params"]["start"] == str(_NOW_NS - 1800 * 10**9)
    assert calls[1]["params"]["since"] == "30m"
    assert calls[2]["params"]["start"] == "30m"
    assert calls[3]["params"]["start"] == "30m"


@pytest.mark.parametrize(
    ("backend", "method"),
    [
        (LokiBackend, "records"),
        (LokiBackend, "streams"),
        (VictoriaLogsBackend, "records"),
        (VictoriaLogsBackend, "streams"),
    ],
)
def test_http_errors_are_not_read_as_empty(
    monkeypatch: pytest.MonkeyPatch,
    backend: type[LokiBackend] | type[VictoriaLogsBackend],
    method: str,
) -> None:
    _fake_http(monkeypatch, _FakeResponse(status=500, payload={}))
    with pytest.raises(requests.HTTPError):
        getattr(backend(_BASE), method)(Q)


def _conftest_backend_keys() -> set[str]:
    """Return the string keys of the `BACKENDS` literal in the e2e conftest."""
    path = Path(__file__).resolve().parents[1] / "e2e" / "conftest.py"
    for node in ast.parse(path.read_text()).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "BACKENDS"
            and isinstance(node.value, ast.Dict)
        ):
            return {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    raise AssertionError("no `BACKENDS: ... = {...}` literal in conftest")


def test_e2e_backends_match_backend_names() -> None:
    """
    Pins: a variant added to one list and not the other fails in `tests`.

    The conftest check raises only when the e2e suite is collected, so
    `nox -s tests` alone would pass a mismatch.
    """
    assert _conftest_backend_keys() == set(BACKEND_NAMES)


_E2E_DIR = Path(__file__).resolve().parents[1] / "e2e"
#: e2e test file -> the domains whose series or streams it checks. Only a
#: file that compares the `collector` label with a literal needs a row; a
#: file checking several domains lists them all, and the gate judges the
#: whole file by the union.
_E2E_FILE_DOMAINS: dict[str, frozenset[str]] = {
    "test_blackbox_delivery.py": frozenset({"blackbox"}),
    "test_container_metrics_delivery.py": frozenset({"container-metrics"}),
    "test_database_delivery.py": frozenset({"database"}),
    "test_fuzz_burst_delivery.py": frozenset({"logs", "metrics"}),
    "test_host_delivery.py": frozenset({"host-metrics"}),
    "test_log_fields_parity.py": frozenset({"logs"}),
    "test_logs_delivery.py": frozenset({"logs"}),
    "test_metrics_delivery.py": frozenset({"metrics"}),
    "test_secret_redaction.py": frozenset({"logs"}),
    "test_snmp_delivery.py": frozenset({"snmp"}),
}
#: Domains a non-reference implementation of the e2e axes can run.
_NON_REFERENCE_DOMAINS = frozenset(METRICS_IMPL_DOMAINS) | frozenset(
    LOGS_IMPL_DOMAINS
)
#: A PromQL or LogQL matcher on the collector label inside a query string.
_COLLECTOR_MATCHER = re.compile(r'\bcollector\s*=~?\s*"([^"]*)"')


def _is_collector_label(node: ast.AST) -> bool:
    """Return whether `node` reads the label: `x["collector"]`, `.get(...)`."""
    if isinstance(node, ast.Subscript):
        return (
            isinstance(node.slice, ast.Constant)
            and node.slice.value == "collector"
        )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "collector"
    )


def _string_literals(operand: ast.expr) -> list[str]:
    """Return a string operand, or the strings of a set/list/tuple operand."""
    elements = (
        operand.elts
        if isinstance(operand, ast.Set | ast.List | ast.Tuple)
        else [operand]
    )
    return [
        e.value
        for e in elements
        if isinstance(e, ast.Constant) and isinstance(e.value, str)
    ]


def _collector_literals(source: str) -> list[str]:
    """Return the string literals a `collector` label is compared with."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.extend(_COLLECTOR_MATCHER.findall(node.value))
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        reads_label = any(
            _is_collector_label(sub) for op in operands for sub in ast.walk(op)
        )
        if reads_label:
            for op in operands:
                found.extend(_string_literals(op))
    return found


def test_collector_literal_finder_sees_both_operand_orders() -> None:
    source = (
        'assert labels["collector"] == "alloy"\n'
        'assert "alloy" != s["metric"]["collector"]\n'
        'assert labels["job"] == "alloy"\n'
        'assert labels["collector"] == stack.collector("metrics")\n'
    )
    assert _collector_literals(source) == ["alloy", "alloy"]


def test_collector_literal_finder_sees_a_set_or_list_operand() -> None:
    source = (
        'assert {s["metric"]["collector"] for s in series} == {"alloy"}\n'
        'assert [s["collector"] for s in rows] == ["alloy"]\n'
        "assert {s['metric']['collector'] for s in series} == "
        '{stack.collector("metrics")}\n'
    )
    assert _collector_literals(source) == ["alloy", "alloy"]


def test_collector_literal_finder_sees_get() -> None:
    source = 'assert labels.get("collector") == "alloy"\n'
    assert _collector_literals(source) == ["alloy"]


def test_collector_literal_finder_sees_a_query_matcher() -> None:
    source = (
        'stack.prom_query(f\'up{{collector="alloy",job="{job}"}}\')\n'
        "stack.prom_query('up{collector=~\"alloy\"}')\n"
        "stack.prom_query('up{job=\"alloy\"}')\n"
    )
    assert _collector_literals(source) == ["alloy", "alloy"]


def test_metrics_impl_domains_equal_the_vmagent_registry_row() -> None:
    assert md.implementations()["vmagent"] == set(METRICS_IMPL_DOMAINS)


def test_logs_impl_domains_equal_the_vector_registry_row() -> None:
    assert md.implementations()["vector"] == set(LOGS_IMPL_DOMAINS)


def test_every_non_reference_implementation_has_an_e2e_axis() -> None:
    """
    Pins: the literal gate below covers every registered implementation.

    A new manifest 14 row without an e2e axis would leave its domains
    outside `_NON_REFERENCE_DOMAINS`, so an `"alloy"` literal there would
    pass `tests` and fail only the e2e session of that implementation.
    """
    registry = md.implementations()
    assert REFERENCE_IMPLEMENTATION == "alloy"
    axes = {
        impl: set(domains)
        for impls, domains in (
            (METRICS_IMPLEMENTATIONS, METRICS_IMPL_DOMAINS),
            (LOGS_IMPLEMENTATIONS, LOGS_IMPL_DOMAINS),
        )
        for impl in impls
        if impl != REFERENCE_IMPLEMENTATION
    }
    assert axes == {
        impl: domains
        for impl, domains in registry.items()
        if impl != REFERENCE_IMPLEMENTATION
    }


def test_e2e_collector_literal_only_where_no_other_implementation_runs() -> (
    None
):
    """
    Pins: a metrics- or logs-domain check expects `stack.collector(...)`.

    e2e_vmagent runs the metrics domain on vmagent and e2e_vector the logs
    domain on Vector, so an `"alloy"` literal in a file of those domains
    would fail that session only; every other domain stays on Alloy.
    """
    offenders = {}
    for path in sorted(_E2E_DIR.glob("test_*.py")):
        if "alloy" not in _collector_literals(path.read_text("utf-8")):
            continue
        domains = _E2E_FILE_DOMAINS.get(path.name)
        if domains is None or domains & _NON_REFERENCE_DOMAINS:
            offenders[path.name] = sorted(domains or {"<unmapped>"})
    assert offenders == {}


def test_e2e_file_domains_are_known() -> None:
    known = set(md.implementations()["alloy"])
    unknown = {
        name: sorted(domains - known)
        for name, domains in _E2E_FILE_DOMAINS.items()
        if domains - known
    }
    assert unknown == {}
