"""
Backend-neutral log queries for the e2e suite.

A `LogQuery` describes what to find; `to_logql` (Loki) and `to_logsql`
(VictoriaLogs) translate it, so a check is written once and runs against
either store. This part is pure: no network, no docker.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

_SCOPE_LABEL = "compose_project"
_SIMPLE_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t"}
_UNESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t"}


@dataclass(frozen=True)
class LogQuery:
    """
    A log selection that both backends can express.

    stream: stream labels that must equal the given values.
    stream_regex: RE2 patterns for stream labels. Loki anchors them fully;
        whether VictoriaLogs does is unverified, so callers use `.*x.*`,
        which matches the same lines either way.
    contains: case-sensitive substring of the log line.
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
        """Reject a label used both as equality and as regex."""
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
    """Quote a string literal; the escape rules are shared by both languages."""
    out = []
    for char in value:
        if char in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:
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
    """
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
        while pos < len(body) and body[pos] in ", ":
            pos += 1
    return result


def _read_quoted(body: str, pos: int, text: str) -> tuple[str, int]:
    """Read an escaped value up to its closing quote; return (value, next pos)."""
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
        elif nxt == "x" and len(body) >= pos + 4:
            chars.append(chr(int(body[pos + 2 : pos + 4], 16)))
            pos += 4
        else:
            raise ValueError(f"bad escape in stream string: {text!r}")
    raise ValueError(f"unterminated value in stream string: {text!r}")


def to_seconds(duration: str) -> float:
    """Convert a duration such as `30m` (units s, m, h) to seconds."""
    units = {"s": 1.0, "m": 60.0, "h": 3600.0}
    return float(duration[:-1]) * units[duration[-1]]
