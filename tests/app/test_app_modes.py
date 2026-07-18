"""Unit tests for the mini-app line renderers (manifest 10.3)."""

import json

import app


def test_emit_period_meets_contract() -> None:
    assert app.EMIT_PERIOD <= 2.0


def test_json_line_is_valid_json_with_metadata_fields() -> None:
    parsed = json.loads(app.json_line(7))
    assert parsed["level"] == "info"
    assert parsed["seq"] == 7
    assert parsed["trace_id"]
    assert parsed["request_id"]


def test_logfmt_line_has_expected_keys() -> None:
    line = app.logfmt_line(7)
    for key in ("level=", "status=", "trace_id=", "request_id=", "seq=7"):
        assert key in line


def test_raw_line_is_plain_text() -> None:
    line = app.raw_line(7)
    assert "=" not in line
    assert not line.startswith("{")


def test_text_with_level_is_a_logfmt_false_positive() -> None:
    # Free text containing "level=" exercises the mixed-v1 heuristics
    # (manifest 10.3.6): the dispatcher may route it to logfmt and must
    # keep it raw on parse failure.
    line = app.text_with_level(7)
    assert "level=" in line
    assert not line.startswith("{")


def test_mixed_cycles_through_all_kinds() -> None:
    kinds = {app.mixed_line(i)[:1] == "{" for i in range(4)}
    lines = [app.mixed_line(i) for i in range(4)]
    assert any(line.startswith("{") for line in lines)
    assert any("msg=" in line and not line.startswith("{") for line in lines)
    assert len(kinds) == 2


def test_parse_burst() -> None:
    assert app.parse_burst("1000:10") == (1000, 10.0)
