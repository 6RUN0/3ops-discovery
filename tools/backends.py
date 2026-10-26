"""
Backend-neutral log queries for the e2e suite.

A `LogQuery` describes what to find; `to_logql` (Loki) and `to_logsql`
(VictoriaLogs) translate it, so a check is written once and runs against
either store. `LokiBackend` and `VictoriaLogsBackend` run a query over
HTTP and return backend-neutral `LogRecord`s; everything else is pure.
"""

from __future__ import annotations

import json
import re
import string
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import requests

_LABEL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SCOPE_LABEL = "compose_project"
#: Storage variants the e2e suite can run against; the first is the default.
BACKEND_NAMES: tuple[str, ...] = ("prometheus-loki", "victoria")
_BACKEND_ENV = "RU_3OPS_DISCOVERY_E2E_BACKEND"
_SIMPLE_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t"}
_DURATION_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0}
_UNESCAPES = {
    "\\": "\\",
    '"': '"',
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
}
#: Go `%q` numeric escapes: letter -> count of hex digits that follow.
_HEX_ESCAPE_DIGITS = {"x": 2, "u": 4, "U": 8}
#: Code points below this, and DEL, are written as `\xNN`.
_FIRST_PRINTABLE = 0x20
_DEL = 0x7F


def selected_backend(env: Mapping[str, str]) -> str:
    """
    Return the e2e storage variant named by `RU_3OPS_DISCOVERY_E2E_BACKEND`.

    Unset means `prometheus-loki`; an unknown name raises ValueError, so a
    typo fails the run instead of silently testing the default store.
    """
    name = env.get(_BACKEND_ENV, BACKEND_NAMES[0])
    if name not in BACKEND_NAMES:
        raise ValueError(
            f"{_BACKEND_ENV}={name!r} is not one of: "
            + ", ".join(BACKEND_NAMES)
        )
    return name


@dataclass(frozen=True)
class LogQuery:
    """
    A log selection that both backends can express.

    stream: stream labels that must equal the given values.
    stream_regex: RE2 patterns for stream labels. Loki anchors them fully;
        whether VictoriaLogs does is unverified, so callers use `.*x.*`,
        which matches the same lines either way.
    contains: non-empty, case-sensitive substring of the log line.
    field_present: the record has this field and it is non-empty.
    scoped: the query must be limited to one compose project (see
        `check_scope`); False declares a deliberately host-wide query.
    """

    stream: Mapping[str, str]
    stream_regex: Mapping[str, str] = field(default_factory=dict)
    contains: str | None = None
    field_present: str | None = None
    scoped: bool = True

    def __post_init__(self) -> None:
        """
        Reject malformed names, an empty `contains` and a doubled label.

        Label and field names are interpolated into the query unquoted, so
        each must match the label-name pattern; `contains=""` renders a
        filter that matches every line.
        """
        names = [*self.stream, *self.stream_regex]
        if self.field_present is not None:
            names.append(self.field_present)
        for name in names:
            if not _LABEL_NAME.fullmatch(name):
                raise ValueError(f"not a label name: {name!r}")
        if self.contains == "":
            raise ValueError("contains must not be empty")
        both = sorted(set(self.stream) & set(self.stream_regex))
        if both:
            raise ValueError(f"label in both stream and stream_regex: {both}")


class UnscopedQueryError(AssertionError):
    """
    A scoped query lacks the compose project label.

    Derives from AssertionError so that `wait_until`, which retries on
    RequestException, KeyError and ValueError, does not swallow it.
    """


def check_scope(query: LogQuery) -> None:
    """Raise UnscopedQueryError when a scoped query has no compose_project."""
    if query.scoped and _SCOPE_LABEL not in query.stream:
        raise UnscopedQueryError(
            f"query {dict(query.stream)} is not limited to one stack: add "
            f"{_SCOPE_LABEL!r} to stream, or pass scoped=False if it is "
            "meant to span the host"
        )


def _quote(value: str) -> str:
    """Quote a string literal; both languages share the escape rules."""
    out = []
    for char in value:
        if char in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[char])
        elif ord(char) < _FIRST_PRINTABLE or ord(char) == _DEL:
            out.append(f"\\x{ord(char):02x}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _stream_selector(query: LogQuery) -> str:
    """Render `{k="v",k2=~"re"}` with all keys sorted together."""
    items = [(key, "=", value) for key, value in query.stream.items()]
    items += [(key, "=~", value) for key, value in query.stream_regex.items()]
    items.sort(key=lambda item: item[0])
    return "{" + ",".join(f"{k}{op}{_quote(v)}" for k, op, v in items) + "}"


def to_logql(query: LogQuery) -> str:
    """Translate a query to LogQL."""
    parts = [_stream_selector(query)]
    if query.contains is not None:
        parts.append(f"|= {_quote(query.contains)}")
    if query.field_present is not None:
        parts.append(f'| {query.field_present}=~".+"')
    return " ".join(parts)


def to_logsql(query: LogQuery) -> str:
    """Translate a query to LogsQL."""
    parts = [_stream_selector(query)]
    if query.contains is not None:
        parts.append(f"_msg:*{_quote(query.contains)}*")
    if query.field_present is not None:
        parts.append(f"{query.field_present}:*")
    return " ".join(parts)


def parse_stream(text: str) -> dict[str, str]:
    r"""
    Parse a stream string such as `{a="b",c="d\\"e"}` into a dict.

    Scans character by character: values may contain commas, braces and
    escaped quotes, which rules out a whole-string regex.
    """
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError(f"not a stream string: {text!r}")
    body = text[1:-1]
    result: dict[str, str] = {}
    pos = 0
    while pos < len(body):
        eq = body.find("=", pos)
        if eq < 0 or body[eq + 1 : eq + 2] != '"':
            raise ValueError(f"malformed stream string: {text!r}")
        key = body[pos:eq].strip()
        value, pos = _read_quoted(body, eq + 2, text)
        result[key] = value
        pos = _skip_pair_separator(body, pos, text)
    return result


def _skip_pair_separator(body: str, pos: int, text: str) -> int:
    """Step over the `,` (and spaces) between pairs; none before the end."""
    while pos < len(body) and body[pos] == " ":
        pos += 1
    if pos == len(body):
        return pos
    if body[pos] != ",":
        raise ValueError(f"malformed stream string: {text!r}")
    pos += 1
    while pos < len(body) and body[pos] == " ":
        pos += 1
    if pos == len(body):
        raise ValueError(f"malformed stream string: {text!r}")
    return pos


def _read_quoted(body: str, pos: int, text: str) -> tuple[str, int]:
    """Read an escaped value up to its closing quote; return (value, pos)."""
    chars: list[str] = []
    while pos < len(body):
        char = body[pos]
        if char == '"':
            return "".join(chars), pos + 1
        if char != "\\":
            chars.append(char)
            pos += 1
            continue
        nxt = body[pos + 1 : pos + 2]
        if nxt in _UNESCAPES:
            chars.append(_UNESCAPES[nxt])
            pos += 2
        elif nxt in _HEX_ESCAPE_DIGITS:
            width = _HEX_ESCAPE_DIGITS[nxt]
            chars.append(_read_hex_escape(body, pos + 2, width, text))
            pos += 2 + width
        else:
            raise ValueError(f"bad escape in stream string: {text!r}")
    raise ValueError(f"unterminated value in stream string: {text!r}")


def _read_hex_escape(body: str, pos: int, width: int, text: str) -> str:
    """Decode `width` hex digits at `pos` into one character."""
    digits = body[pos : pos + width]
    if len(digits) != width or not set(digits) <= set(string.hexdigits):
        raise ValueError(f"bad escape in stream string: {text!r}")
    try:
        return chr(int(digits, 16))
    except ValueError:
        raise ValueError(f"bad escape in stream string: {text!r}") from None


def to_seconds(duration: str) -> float:
    """Convert a duration such as `30m` (units s, m, h) to seconds."""
    number, unit = duration[:-1], duration[-1:]
    if unit not in _DURATION_UNITS:
        raise ValueError(f"bad duration {duration!r}: unit must be s, m or h")
    try:
        return float(number) * _DURATION_UNITS[unit]
    except ValueError:
        raise ValueError(
            f"bad duration {duration!r}: no number before the unit"
        ) from None


@dataclass(frozen=True)
class LogRecord:
    """
    One log entry as either backend returns it.

    ts: nanoseconds since the epoch, as a decimal string.
    line: the log line exactly as stored.
    stream: indexed stream labels.
    fields: non-indexed fields - Loki structured metadata; for
        VictoriaLogs every field except the internal `_*` ones and the
        stream labels.
    """

    ts: str
    line: str
    stream: Mapping[str, str]
    fields: Mapping[str, str]


class LogsBackend(Protocol):
    """Read access to a log store; every method calls `check_scope` first."""

    def records(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[LogRecord]:
        """All records matching the query, ascending by `ts`."""
        ...

    def entries(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[tuple[str, str]]:
        """`(ts, line)` of every record, ascending by `ts`."""
        ...

    def streams(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[dict[str, str]]:
        """Label sets of the streams matching the query's stream selector."""
        ...


def _reject_line_filters(query: LogQuery) -> None:
    """Refuse filters a series/streams lookup cannot apply on Loki."""
    if query.contains is not None or query.field_present is not None:
        raise TypeError(
            "streams() selects by stream labels only; drop contains and "
            f"field_present from {query!r}"
        )


_LOKI_PAGE = 5000
_LOKI_CATEGORIZE = {"X-Loki-Response-Encoding-Flags": "categorize-labels"}


class LokiBackend:
    """`LogsBackend` over the Loki HTTP API."""

    def __init__(self, url: str) -> None:
        """Bind to a Loki base URL such as `http://127.0.0.1:3100`."""
        self.url = url

    def records(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[LogRecord]:
        """
        Page forward through query_range, `_LOKI_PAGE` entries at a time.

        The categorize-labels flag makes Loki return structured metadata
        apart from the stream labels, as the third element of each value.
        """
        check_scope(query)
        logql = to_logql(query)
        end_ns = time.time_ns()
        start_ns = end_ns - int(to_seconds(since) * 1e9)
        records: list[LogRecord] = []
        while True:
            resp = requests.get(
                f"{self.url}/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "start": str(start_ns),
                    "end": str(end_ns),
                    "limit": str(_LOKI_PAGE),
                    "direction": "forward",
                },
                headers=_LOKI_CATEGORIZE,
                timeout=30,
            )
            resp.raise_for_status()
            batch = loki_result_to_records(resp.json()["data"]["result"])
            records.extend(batch)
            if len(batch) < _LOKI_PAGE:
                return sorted(records, key=lambda r: int(r.ts))
            start_ns = max(int(r.ts) for r in batch) + 1

    def entries(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[tuple[str, str]]:
        """`(ts, line)` of every record, ascending by `ts`."""
        return [(r.ts, r.line) for r in self.records(query, since=since)]

    def streams(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[dict[str, str]]:
        """Label sets from `/loki/api/v1/series`."""
        check_scope(query)
        _reject_line_filters(query)
        resp = requests.get(
            f"{self.url}/loki/api/v1/series",
            params={"match[]": to_logql(query), "since": since},
            timeout=10,
        )
        resp.raise_for_status()
        return [dict(labels) for labels in resp.json()["data"]]


def loki_result_to_records(
    result: Iterable[Mapping[str, Any]],
) -> list[LogRecord]:
    """
    Flatten a categorized query_range `data.result` into records.

    Each value is `[ts, line]` or `[ts, line, {"structuredMetadata":
    {...}, "parsed": {...}}]`; only structured metadata becomes `fields`.
    """
    records = []
    for stream in result:
        labels = dict(stream["stream"])
        for ts, line, *rest in stream["values"]:
            extra = rest[0] if rest else {}
            records.append(
                LogRecord(
                    ts=ts,
                    line=line,
                    stream=labels,
                    fields=dict(extra.get("structuredMetadata") or {}),
                )
            )
    return records


_VL_INTERNAL = frozenset({"_time", "_msg", "_stream", "_stream_id"})
_NS_DIGITS = 9


def _rfc3339_to_ns(stamp: str) -> str:
    """
    Convert `2026-10-25T00:00:01.5Z` to nanoseconds as a string.

    The fraction is read as text and padded to 9 digits: a float would
    lose the low digits of a nanosecond timestamp.
    """
    if not stamp.endswith("Z"):
        raise ValueError(f"expected a UTC timestamp ending in Z: {stamp!r}")
    whole, _, frac = stamp[:-1].partition(".")
    if len(frac) > _NS_DIGITS or not (frac == "" or frac.isdigit()):
        raise ValueError(f"bad fractional seconds in {stamp!r}")
    seconds = int(
        datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S")
        .replace(tzinfo=UTC)
        .timestamp()
    )
    return str(seconds * 10**_NS_DIGITS + int(frac.ljust(_NS_DIGITS, "0")))


def parse_json_lines(text: str) -> list[dict[str, Any]]:
    """
    Parse a JSON-lines body, one object per non-empty line.

    A bad line, or one that is valid JSON but not an object, raises
    ValueError naming its 1-based number and text: the bare decoder error
    gives only a character offset into the whole body, and a non-object
    row would fail later as a TypeError with no line attached.
    """
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"bad JSON on line {number} of the response: {line!r}"
            ) from exc
        if isinstance(row, dict):
            rows.append(row)
            continue
        raise ValueError(
            f"line {number} of the response is not a JSON object: {line!r}"
        )
    return rows


def victorialogs_rows_to_records(
    rows: Iterable[Mapping[str, str]],
) -> list[LogRecord]:
    """Turn VictoriaLogs query rows into records, ascending by `ts`."""
    records = []
    for row in rows:
        stream = parse_stream(row["_stream"])
        records.append(
            LogRecord(
                ts=_rfc3339_to_ns(row["_time"]),
                line=row["_msg"],
                stream=stream,
                fields={
                    key: value
                    for key, value in row.items()
                    if key not in _VL_INTERNAL and key not in stream
                },
            )
        )
    return sorted(records, key=lambda r: int(r.ts))


class VictoriaLogsBackend:
    """`LogsBackend` over the VictoriaLogs HTTP API."""

    def __init__(self, url: str) -> None:
        """Bind to a VictoriaLogs base URL such as `http://127.0.0.1:9428`."""
        self.url = url

    def records(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[LogRecord]:
        """
        One `/select/logsql/query` call over the window, without `limit`.

        With `limit` VictoriaLogs returns the newest matches, not the
        first ones, so the whole window is read and sorted here.
        """
        check_scope(query)
        resp = requests.get(
            f"{self.url}/select/logsql/query",
            params={"query": to_logsql(query), "start": since, "end": "now"},
            timeout=30,
        )
        resp.raise_for_status()
        return victorialogs_rows_to_records(parse_json_lines(resp.text))

    def entries(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[tuple[str, str]]:
        """`(ts, line)` of every record, ascending by `ts`."""
        return [(r.ts, r.line) for r in self.records(query, since=since)]

    def streams(
        self, query: LogQuery, *, since: str = "30m"
    ) -> list[dict[str, str]]:
        """Label sets from `/select/logsql/streams`."""
        check_scope(query)
        _reject_line_filters(query)
        resp = requests.get(
            f"{self.url}/select/logsql/streams",
            params={"query": to_logsql(query), "start": since, "end": "now"},
            timeout=10,
        )
        resp.raise_for_status()
        return [parse_stream(item["value"]) for item in resp.json()["values"]]
