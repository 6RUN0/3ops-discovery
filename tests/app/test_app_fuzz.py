"""Unit tests for the fuzz corpus generator (manifest 10.3)."""

import json

import pytest

import app


def _flat_corpus(upto: int) -> list[bytes]:
    return [p for seq in range(upto) for p in app.fuzz_payloads(seq)]


def _is_invalid_utf8(payload: bytes) -> bool:
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def test_corpus_contains_invalid_utf8() -> None:
    invalid = [
        p for p in _flat_corpus(app.FUZZ_MARKER_EVERY) if _is_invalid_utf8(p)
    ]
    assert invalid


def test_corpus_contains_huge_line() -> None:
    assert any(len(p) > 200_000 for p in _flat_corpus(8))


def test_corpus_contains_broken_json() -> None:
    def broken(p: bytes) -> bool:
        try:
            text = p.decode()
        except UnicodeDecodeError:
            return False
        if not text.lstrip().startswith("{"):
            return False
        try:
            json.loads(text)
        except json.JSONDecodeError:
            return True
        return False

    assert any(broken(p) for p in _flat_corpus(8))


def test_marker_line_every_nth_seq() -> None:
    markers = [
        p
        for p in app.fuzz_payloads(app.FUZZ_MARKER_EVERY)
        if b"fuzz-marker" in p
    ]
    assert len(markers) == 1
    parsed = json.loads(markers[0])
    assert parsed["event"] == "fuzz-marker"
    assert parsed["marker"] == app.FUZZ_MARKER_EVERY


def test_no_marker_on_other_seqs() -> None:
    assert not any(b"fuzz-marker" in p for p in app.fuzz_payloads(1))


def test_payloads_contain_no_newlines_inside() -> None:
    for payload in _flat_corpus(8):
        assert b"\n" not in payload


def test_counter_never_fuzzed() -> None:
    # Guard the invariant, not the implementation: extremes go to the
    # gauge only (prometheus_client rejects negative counter incs).
    with pytest.raises(ValueError, match="Counters can only"):
        app.EVENTS.inc(-1)
