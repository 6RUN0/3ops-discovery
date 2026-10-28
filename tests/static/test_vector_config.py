"""
Vector implementation (implementations/vector/) vs the manifest.

The Vector config is a second implementation of the logs domain, so it
answers to the same tables as the reference: the indexed-field allowlist
and its metadata-only origin (6.2), the log profiles and their fields
(8.3), the opt-out literal and the unknown-profile fallback (10.3), the
14.1 defaults and the section 14 registry row with its pinned image tag.

Every extractor also gets a broken config it must reject: a gate whose
extractor reads the wrong thing passes on any config.
"""

import copy
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import nox
import noxfile as nx
import pytest
import yaml

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md
from tests.static import vector_config as vc

#: Section 14.1 parameters Vector reads for the logs domain and its output.
LOGS_ENV = {
    "RU_3OPS_DISCOVERY_DOCKER_HOST",
    "RU_3OPS_DISCOVERY_LOKI_PUSH_URL",
    "RU_3OPS_DISCOVERY_HOSTNAME",
}
OPTOUT_LABEL = "ru.3ops.discovery.logs.enabled"
#: Labels every stream carries whatever the container declares.
ALWAYS_PRESENT = {"collector", "host", "source", "container", "log_profile"}
INTERPOLATION_FLAG = "--dangerously-allow-env-var-interpolation"
#: RE2's \s as an explicit ASCII class (Go regexp/syntax: [\t\n\f\r ]).
RE2_SPACE = "[ \\t\\n\\f\\r]"
#: Rust regex Perl classes that match beyond ASCII, unlike RE2's.
UNICODE_CLASSES = ("\\s", "\\S", "\\d", "\\D", "\\w", "\\W", "\\b", "\\B")


def _config() -> dict[str, Any]:
    return copy.deepcopy(vc.load_vector_config(vc.CONFIG))


def _transform(config: dict[str, Any], kind: str) -> dict[str, Any]:
    matches = [
        body
        for body in config["transforms"].values()
        if body.get("type") == kind
    ]
    assert len(matches) == 1
    body: dict[str, Any] = matches[0]
    return body


def _writer(config: dict[str, Any]) -> dict[str, Any]:
    name = vc.stream_labels_writer(config)[0]
    body: dict[str, Any] = config["transforms"][name]
    return body


# --- Log profiles (8.3, 10.3.2, 10.3.4) ---


def test_profile_allowlist_matches_manifest() -> None:
    allowlist = vc.profile_allowlist()
    assert len(allowlist) == len(set(allowlist))
    assert set(allowlist) == set(md.log_profile_fields())
    assert vc.fallback_profile() == "raw-v1"
    # raw-v1 is the pass-through: every other profile has a route.
    assert set(vc.routed_profiles().values()) == set(allowlist) - {"raw-v1"}


def test_unknown_profile_is_logged_by_the_collector() -> None:
    # 10.3.4 items 1-3: keep collecting, apply raw-v1, say so in the
    # collector's own log.
    assert 'level: "warn"' in vc.unknown_profile_branch()
    assert "log(" in vc.unknown_profile_branch()


def test_allowlist_gate_catches_a_missing_fallback() -> None:
    config = _config()
    writer = _writer(config)
    writer["source"] = writer["source"].replace(
        'profile = "raw-v1"\n', 'profile = "generic-json-v1"\n'
    )
    assert vc.fallback_profile(config) == "generic-json-v1"
    writer["source"] = re.sub(
        r'(?m)^\s*profile = "generic-json-v1"\n', "", writer["source"]
    )
    with pytest.raises(vc.VectorConfigError, match="0 fallback"):
        vc.fallback_profile(config)


def test_allowlist_gate_reads_the_literal_list() -> None:
    config = _config()
    writer = _writer(config)
    writer["source"] = writer["source"].replace(
        '"mixed-v1", ', '"mixed-v1", "nginx-json-v1", '
    )
    assert "nginx-json-v1" in vc.profile_allowlist(config)


def test_profile_fields_match_manifest_table() -> None:
    table = md.log_profile_fields()
    branches = vc.profile_branches()
    for profile, outputs in branches.items():
        for output, (_, fields) in outputs.items():
            assert fields == table[profile], f"{profile} via {output}"
    # mixed-v1: one branch per parser, each with the full 8.3 set.
    assert {kind for kind, _ in branches["mixed-v1"].values()} == {
        "json",
        "logfmt",
    }
    assert {kind for kind, _ in branches["generic-json-v1"].values()} == {
        "json"
    }
    assert {kind for kind, _ in branches["generic-logfmt-v1"].values()} == {
        "logfmt"
    }
    for profile in ("python-stacktrace-v1", "java-stacktrace-v1"):
        assert {kind for kind, _ in branches[profile].values()} == {None}


def test_profile_fields_gate_catches_a_dropped_field() -> None:
    config = _config()
    for body in config["transforms"].values():
        if vc.parser_kind(body) == "logfmt":
            body["source"] = body["source"].replace('"status", ', "")
    table = md.log_profile_fields()
    fields = vc.profile_branches(config)["generic-logfmt-v1"]
    assert all(f != table["generic-logfmt-v1"] for _, f in fields.values())


def test_profile_fields_gate_catches_a_branch_without_its_parser() -> None:
    config = _config()
    route, _ = vc.profile_route(config)
    for body in config["transforms"].values():
        if vc.parser_kind(body) == "logfmt":
            body["inputs"].remove(f"{route}.mixed-v1-logfmt")
    config["sinks"][vc.logs_sink(config)[0]]["inputs"].append(
        f"{route}.mixed-v1-logfmt"
    )
    kinds = {k for k, _ in vc.profile_branches(config)["mixed-v1"].values()}
    assert kinds == {"json", None}


def test_parser_kind_rejects_two_parsers_in_one_remap() -> None:
    body = {
        "type": "remap",
        "source": "a = parse_json(string(.message))\n"
        "b = parse_regex(string(.message), r'x')\n",
    }
    with pytest.raises(vc.VectorConfigError, match="two parsers"):
        vc.parser_kind(body)


@pytest.mark.parametrize("call", ["parse_logfmt", "parse_key_value"])
def test_parser_kind_rejects_the_lossy_logfmt_parsers(call: str) -> None:
    # Both disagree with the reference: `err= level=warn` loses level,
    # a standalone key becomes "true", a duplicate key an array.
    body = {"type": "remap", "source": f"p = {call}(string(.message))\n"}
    with pytest.raises(vc.VectorConfigError, match=call):
        vc.parser_kind(body)


def test_logfmt_remap_unquotes_only_quoted_values() -> None:
    # The pair regex captures the inside of a quoted value; JSON string
    # rules unescape it, as go-logfmt does (`"a \\"b\\""` -> `a "b"`).
    source = next(
        body["source"]
        for body in _config()["transforms"].values()
        if vc.parser_kind(body) == "logfmt"
    )
    assert 'parse_json("\\"" + quoted + "\\"")' in source
    assert "found = set!(found, [key], value)" in source


#: Structured metadata of Alloy v1.21.2 stage.logfmt with the 050 mapping,
#: measured live (task-2-report.md, fix round 1). go-logfmt stops at the
#: first malformed pair and keeps the pairs before it.
ALLOY_LOGFMT = {
    "err= level=warn": {"level": "warn"},
    "time=1 level= status=5": {"level": "", "status": "5"},
    "Changing log level to debug": {"level": ""},
    "level=a level=b": {"level": "b"},
    'msg="hello world a=b" level=info': {"level": "info"},
    'level="quoted value" status=200': {
        "level": "quoted value",
        "status": "200",
    },
    "level": {"level": ""},
    "level=info status": {"level": "info", "status": ""},
    'request_id="x y=z" level=debug': {
        "level": "debug",
        "request_id": "x y=z",
    },
    "a=b=c level=info": {},
    'level="unterminated status=1': {},
    "status=200 level=info trace_id=": {
        "level": "info",
        "status": "200",
        "trace_id": "",
    },
    'level="a \\"b\\" \\\\ c"': {"level": 'a "b" \\ c'},
    "level=info a=b=c": {"level": "info"},
    'level=info x="unterminated': {"level": "info"},
    'level=info "quotedkey"=1': {"level": "info"},
    "  level=info   status=7  ": {"level": "info", "status": "7"},
    'level="x\\ny" status=3': {"level": "x\ny", "status": "3"},
    'level="a\tb" status=9': {},
    # Every byte <= 0x20 separates, a closing quote needs no separator,
    # and a Unicode space such as NBSP is part of a value (rereview N1).
    "level=\x1b[32minfo\x1b[0m status=200": {"level": "", "status": "200"},
    "level=info\x01status=5": {"level": "info", "status": "5"},
    'level="a"status=5': {"level": "a", "status": "5"},
    "level=a\u00a0status=5": {},
}


def _vector_logfmt(line: str) -> dict[str, str]:
    """Run the remap's two regexes and its value rules in Python."""
    prefix_regex, pair_regex = vc.logfmt_grammar()
    fields = md.log_profile_fields()["generic-logfmt-v1"]
    match = re.match(prefix_regex, line)
    assert match is not None
    found: dict[str, str] = {}
    for pair in re.finditer(pair_regex, match.group("prefix")):
        if pair["key"] in fields:
            quoted = pair["quoted"]
            found[pair["key"]] = (
                json.loads(f'"{quoted}"')
                if quoted is not None
                else pair["bare"] or ""
            )
    return found


@pytest.mark.parametrize("line", sorted(ALLOY_LOGFMT))
def test_logfmt_grammar_matches_the_reference(line: str) -> None:
    assert _vector_logfmt(line) == ALLOY_LOGFMT[line]


def test_json_null_gives_no_metadata_entry() -> None:
    # Alloy's json stage skips a null result but keeps "" (measured).
    source = next(
        body["source"]
        for body in _config()["transforms"].values()
        if vc.parser_kind(body) == "json"
    )
    assert "includes(fields, key) && value != null" in source


def test_routed_profiles_rejects_a_condition_on_something_else() -> None:
    config = _config()
    _transform(config, "route")["route"]["generic-json-v1"] = "true"
    with pytest.raises(vc.VectorConfigError, match="names no profile"):
        vc.routed_profiles(config)


def test_mixed_branches_are_exclusive() -> None:
    # A route sends an event to EVERY output whose condition holds, so a
    # line like {"msg":"raised level=high"} would be parsed twice and
    # delivered twice unless the logfmt branch excludes JSON-shaped
    # lines (10.3.6).
    _, routes = vc.profile_route()
    json_anchor = f"match(string(.message) ?? \"\", r'^{RE2_SPACE}*\\{{')"
    assert json_anchor in routes["mixed-v1-json"]
    assert f"!{json_anchor}" in routes["mixed-v1-logfmt"]
    assert f"!{json_anchor}" not in routes["mixed-v1-json"]
    assert f"(^|{RE2_SPACE})(level|msg|status)=" in routes["mixed-v1-logfmt"]


def _vrl_regexes(node: Any) -> list[str]:
    """Return every raw regex literal in the config's string values."""
    if isinstance(node, dict):
        return [r for value in node.values() for r in _vrl_regexes(value)]
    if isinstance(node, list):
        return [r for value in node for r in _vrl_regexes(value)]
    return re.findall(r"r'([^']*)'", node) if isinstance(node, str) else []


def _unicode_classes(config: dict[str, Any]) -> set[str]:
    """Return the Unicode-aware class escapes in the config's regexes."""
    return {
        escape
        for regex in _vrl_regexes(config)
        for escape in re.findall(r"\\.", regex)
        if escape in UNICODE_CLASSES
    }


def test_vrl_regexes_use_ascii_classes() -> None:
    r"""
    Pins RE2 semantics: Rust's \s, \d, \w and \b are Unicode-aware.

    The reference's RE2 classes are ASCII, so a Unicode class would let
    NBSP open a JSON branch or Arabic-Indic digits open a traceback.
    """
    assert len(_vrl_regexes(_config())) >= 5
    assert _unicode_classes(_config()) == set()


def test_ascii_class_gate_reads_the_escapes() -> None:
    r"""Pins the escape scan: \\s is a literal backslash, \s a class."""
    config = _config()
    reduce = _transform(config, "reduce")
    reduce["starts_when"]["source"] = (
        r"match(.m, r'a\\sb') || match(.m, r'\d')"
    )
    assert _unicode_classes(config) == {"\\d"}


# --- Stream labels (6.1, 6.2) ---


def test_stream_labels_within_manifest_allowlist() -> None:
    keys = vc.stream_label_keys()
    assert keys <= md.loki_label_allowlist()
    assert keys >= ALWAYS_PRESENT
    assert vc.sink_label_field() == vc.STREAM_LABELS_FIELD
    assert vc.sink_metadata_field() == vc.STRUCTURED_METADATA_FIELD


def test_collector_and_source_are_constants() -> None:
    assert vc.static_stream_labels() == {
        "source": "docker",
        "collector": "vector",
    }
    assert "vector" in md.implementations()


def test_stream_labels_come_from_metadata_only() -> None:
    assert vc.stream_label_problems() == []


def test_label_origin_gate_catches_a_writer_that_reads_the_line() -> None:
    config = _config()
    writer = _writer(config)
    writer["source"] += 'indexed.level = string(.message) ?? ""\n'
    assert vc.stream_label_problems(config) != []


def test_label_origin_gate_catches_a_writer_after_a_parser() -> None:
    config = _config()
    writer_name = vc.stream_labels_writer(config)[0]
    parser = next(
        name
        for name, body in config["transforms"].items()
        if vc.parser_kind(body) == "json"
    )
    config["transforms"][writer_name]["inputs"] = [parser]
    assert any(
        "before" in p or "without" in p
        for p in vc.stream_label_problems(config)
    )


def _append_to_parser(config: dict[str, Any], line: str) -> None:
    for body in config["transforms"].values():
        if vc.parser_kind(body) == "json":
            body["source"] += line + "\n"


@pytest.mark.parametrize(
    "line",
    [
        ".stream_labels = merge(.stream_labels, parsed)",
        '.stream_labels.host = string(parsed.host) ?? "x"',
        ".stream_labels |= parsed",
        "del(.stream_labels.host)",
    ],
)
def test_label_origin_gate_catches_a_parser_touching_labels(line: str) -> None:
    config = _config()
    _append_to_parser(config, line)
    assert any("touches" in p for p in vc.stream_label_problems(config))


@pytest.mark.parametrize(
    "line",
    [
        ". |= parsed",
        ". = merge(., parsed)",
        ". = parsed",
        '. = set!(., ["stream_labels", "host"], "x")',
        '."stream_labels".host = "x"',
        '. = merge(., {"stream_labels": parsed})',
        "del(.)",
    ],
)
def test_label_origin_gate_catches_a_parser_writing_the_root(
    line: str,
) -> None:
    # `. |= parse_json!(.message)` is the common VRL idiom; with it a line
    # {"stream_labels": {...}} would set the stream labels.
    config = _config()
    _append_to_parser(config, line)
    assert vc.stream_label_problems(config) != []


@pytest.mark.parametrize(
    "line",
    [
        "indexed = merge(indexed, container_labels)",
        "indexed |= container_labels",
        "del(indexed.host)",
    ],
)
def test_label_origin_gate_catches_a_writer_merging_keys(line: str) -> None:
    config = _config()
    writer = _writer(config)
    writer["source"] = writer["source"].replace(
        "indexed.log_profile = profile\n",
        f"indexed.log_profile = profile\n{line}\n",
    )
    assert any("key by key" in p for p in vc.stream_label_problems(config))


def test_label_origin_gate_catches_a_reduce_merging_labels() -> None:
    config = _config()
    _transform(config, "reduce")["merge_strategies"]["stream_labels"] = (
        "concat"
    )
    assert any("touches" in p for p in vc.stream_label_problems(config))


def test_label_origin_gate_catches_a_second_writer() -> None:
    config = _config()
    for body in config["transforms"].values():
        if vc.parser_kind(body) == "json":
            body["source"] += f".{vc.STREAM_LABELS_FIELD} = parsed\n"
    with pytest.raises(vc.VectorConfigError, match="2 transforms write"):
        vc.stream_labels_writer(config)


@pytest.mark.parametrize(
    "line",
    [
        '.stream_labels.image = string(.image) ?? ""',
        '."stream_labels".image = "x"',
        '. = set!(., ["stream_labels", "image"], "x")',
        ".stream_labels = container_labels",
    ],
)
def test_label_origin_gate_catches_a_writer_writing_the_field_directly(
    line: str,
) -> None:
    """Pins 6.2: a key written past the vetted variable escapes the keys."""
    config = _config()
    name = vc.stream_labels_writer(config)[0]
    _writer(config)["source"] += line + "\n"
    assert vc.stream_label_keys(config) <= md.loki_label_allowlist()
    assert f"{name} writes .stream_labels directly" in (
        vc.stream_label_problems(config)
    )


def test_label_origin_gate_catches_a_writer_writing_the_root() -> None:
    """Pins 6.2: a root merge in the writer can replace the labels whole."""
    config = _config()
    name = vc.stream_labels_writer(config)[0]
    _writer(config)["source"] += ". |= container_labels\n"
    assert f"{name} writes the event root" in vc.stream_label_problems(config)


def test_structured_metadata_is_written_whole() -> None:
    """Pins 8.3: metadata keys come only from the fields-filtered object."""
    assert vc.metadata_write_problems() == []


@pytest.mark.parametrize(
    "line",
    [
        '.structured_metadata.image = string(.image) ?? ""',
        '. = set!(., ["structured_metadata", "x"], "y")',
        ".structured_metadata = merge(.structured_metadata, parsed)",
    ],
)
def test_metadata_gate_catches_a_key_by_key_write(line: str) -> None:
    """Pins 8.3: a key added past the fields filter leaves the table."""
    config = _config()
    _append_to_parser(config, line)
    parser = next(
        name
        for name, body in config["transforms"].items()
        if vc.parser_kind(body) == "json"
    )
    assert vc.metadata_write_problems(config) == [
        f"{parser} writes .structured_metadata key by key"
    ]


def test_metadata_gate_catches_a_reduce_merging_metadata() -> None:
    """Pins 8.3: a reduce merge strategy can join metadata of many lines."""
    config = _config()
    reduce = _transform(config, "reduce")
    reduce["merge_strategies"]["structured_metadata"] = "concat"
    name = next(
        key for key, body in config["transforms"].items() if body is reduce
    )
    assert vc.metadata_write_problems(config) == [
        f"{name} writes .structured_metadata key by key"
    ]


def test_sink_template_gate_rejects_per_label_templates() -> None:
    # Per-label templates log a WARN on every event whose field is
    # absent; the whole-object template drops absent labels silently.
    config = _config()
    sink = config["sinks"][vc.logs_sink(config)[0]]
    sink["labels"] = {"host": "{{ stream_labels.host }}"}
    with pytest.raises(vc.VectorConfigError, match="one '\\*' template"):
        vc.sink_label_field(config)


def test_absent_labels_are_left_out_not_emptied() -> None:
    # R4: a container without environment/team/logs.service gets no such
    # label at all; each is assigned only behind a non-empty check.
    _, source, var = vc.stream_labels_writer()
    for key in vc.stream_label_keys() - set(vc.static_stream_labels()):
        if key in ("host", "log_profile"):
            continue
        assert f'!= "" {{ {var}.{key} = ' in source, key


# --- Opt-out (10.3.1, 10.3.5) ---


def test_optout_matches_only_literal_false() -> None:
    assert OPTOUT_LABEL in md.domain_labels("10.3.5")
    assert vc.optout_condition() == f'.label."{OPTOUT_LABEL}" != "false"'


@pytest.mark.parametrize(
    "condition",
    [
        f'.label."{OPTOUT_LABEL}" == "true"',
        f'downcase(string(.label."{OPTOUT_LABEL}") ?? "") != "false"',
        f'.label."{OPTOUT_LABEL}" != "False"',
    ],
)
def test_optout_gate_catches_another_condition(condition: str) -> None:
    config = _config()
    _transform(config, "filter")["condition"] = condition
    assert vc.optout_condition(config) != (
        f'.label."{OPTOUT_LABEL}" != "false"'
    )


def test_optout_gate_catches_a_bypass() -> None:
    config = _config()
    source = next(iter(config["sources"]))
    config["sinks"][vc.logs_sink(config)[0]]["inputs"].append(source)
    with pytest.raises(vc.VectorConfigError, match="not one filter"):
        vc.optout_condition(config)


# --- Multiline (8.3) ---


def _reference_multiline() -> dict[str, str]:
    stages = ac.multiline_stages()
    assert stages["python-stacktrace-v1"] == stages["java-stacktrace-v1"]
    return stages["python-stacktrace-v1"]


def test_multiline_reduce_parameters() -> None:
    reference = _reference_multiline()
    route, _ = vc.profile_route()
    params = vc.multiline()
    assert params["inputs"] == {
        f"{route}.{output}"
        for output, profile in vc.routed_profiles().items()
        if profile in ("python-stacktrace-v1", "java-stacktrace-v1")
    }
    assert params["group_by"] == ["container_id"]
    # River escapes each backslash; the VRL raw string does not, and
    # spells RE2's ASCII \d as [0-9].
    firstline = reference["firstline"].replace("\\\\", "\\")
    assert params["anchor"] == firstline.replace("\\d", "[0-9]")
    assert params["max_events"] == int(reference["max_lines"]) == 128
    assert reference["max_wait_time"] == "10s"
    assert params["expire_after_ms"] == 10000
    assert params["merge_strategies"] == {"message": "concat_newline"}


def test_multiline_gate_accepts_the_string_condition_form() -> None:
    config = _config()
    reduce = _transform(config, "reduce")
    reduce["starts_when"] = reduce["starts_when"]["source"]
    assert vc.multiline(config)["anchor"] == vc.multiline()["anchor"]


def test_multiline_gate_catches_an_end_condition() -> None:
    config = _config()
    _transform(config, "reduce")["ends_when"] = "true"
    with pytest.raises(vc.VectorConfigError, match="ends_when"):
        vc.multiline(config)


def test_multiline_gate_catches_a_second_reduce() -> None:
    config = _config()
    config["transforms"]["extra"] = copy.deepcopy(_transform(config, "reduce"))
    with pytest.raises(vc.VectorConfigError, match="2 reduce transforms"):
        vc.multiline(config)


# --- Environment (14.1) and interpolation ---


def test_env_defaults_match_manifest() -> None:
    table = md.env_defaults()
    defaults = vc.entrypoint_defaults()
    assert set(defaults) == LOGS_ENV
    for name, default in defaults.items():
        if name != "RU_3OPS_DISCOVERY_HOSTNAME":
            assert default == table[name]
    # The 14.1 cell is prose ("the collector's hostname"), not a value.
    assert defaults["RU_3OPS_DISCOVERY_HOSTNAME"] == "$(hostname)"


def test_refresh_interval_is_not_read() -> None:
    # docker_logs follows Docker events, it does not poll, so the 14.1
    # refresh interval has nothing to set.
    for path in (vc.CONFIG, vc.ENTRYPOINT):
        text = path.read_text(encoding="utf-8")
        assert "RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL" not in text


def test_hostname_fallback_lives_in_the_entrypoint_only() -> None:
    text = vc.CONFIG.read_text(encoding="utf-8")
    assert "get_hostname" not in text
    assert vc.env_reads(text) == {"RU_3OPS_DISCOVERY_HOSTNAME"}
    assert 'get_env_var!("RU_3OPS_DISCOVERY_HOSTNAME")' in text


def test_defaults_live_in_the_entrypoint_only() -> None:
    text = vc.CONFIG.read_text(encoding="utf-8")
    assert vc.defaulted_interpolations(text) == set()
    assert vc.interpolations(text)


def test_no_bare_dollar_in_the_config() -> None:
    assert vc.bare_dollars(vc.CONFIG.read_text(encoding="utf-8")) == []


def test_bare_dollar_gate_flags_an_unescaped_anchor() -> None:
    text = "a: '${X}'\nb: match(s, r'^x$')\nc: r'^x$$'\nd: $NAME\n"
    assert vc.bare_dollars(text) == ["b: match(s, r'^x$')", "d: $NAME"]
    assert vc.interpolations(text) == {"X", "NAME"}


@pytest.mark.parametrize(
    ("text", "names"),
    [("$A$$B", {"A"}), ("$$$A", {"A"}), ("$$A", set()), ("${A$$}", set())],
)
def test_escaped_dollar_ends_a_name(text: str, names: set[str]) -> None:
    """Pins Vector's scan: ``$$`` is a literal ``$`` that ends a name."""
    assert vc.interpolations(text) == names


def test_escaped_dollar_inside_braces_is_no_interpolation() -> None:
    """Pins the gates on ``${...$$...}``: neither a variable nor a default."""
    text = "a: ${$$}\nb: ${A$$}\n"
    assert vc.bare_dollars(text) == ["a: ${$$}", "b: ${A$$}"]
    assert vc.defaulted_interpolations("a: ${A$$:-x}") == set()


def test_interpolation_gate_sees_inline_defaults() -> None:
    assert vc.defaulted_interpolations("a: ${A:-x} b: ${B-y} c: ${C}") == {
        "A",
        "B",
    }


def test_entrypoint_defaults_errors_name_the_problem() -> None:
    with pytest.raises(vc.VectorConfigError, match="X has diverging"):
        vc.entrypoint_defaults(
            "${RU_3OPS_DISCOVERY_X:-a} ${RU_3OPS_DISCOVERY_X:-b}"
        )
    with pytest.raises(vc.VectorConfigError, match="no \\$\\{NAME"):
        vc.entrypoint_defaults("nothing here")


# --- entrypoint.sh, run with a stub vector binary ---


def _stub_bin(tmp_path: Path, hostname: str = "echo stub-host") -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    vector = bin_dir / "vector"
    vector.write_text(
        '#!/bin/sh\nprintf "arg=%s\\n" "$@"\nenv\n', encoding="utf-8"
    )
    host = bin_dir / "hostname"
    host.write_text(f"#!/bin/sh\n{hostname}\n", encoding="utf-8")
    for script in (vector, host):
        script.chmod(0o755)
    return bin_dir


def _run_entrypoint(
    bin_dir: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", str(vc.ENTRYPOINT), *args],
        env={"PATH": f"{bin_dir}:{os.defpath}", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def _vector_env(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    assert result.returncode == 0, result.stderr
    return dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if "=" in line and not line.startswith("arg=")
    )


def _vector_args(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [
        line.removeprefix("arg=")
        for line in result.stdout.splitlines()
        if line.startswith("arg=")
    ]


def test_entrypoint_applies_defaults_and_splits_the_push_url(
    tmp_path: Path,
) -> None:
    result = _run_entrypoint(_stub_bin(tmp_path), {}, "validate")
    env = _vector_env(result)
    docker_host = env["RU_3OPS_DISCOVERY_DOCKER_HOST"]
    assert docker_host == "unix:///var/run/docker.sock"
    assert env["RU_3OPS_DISCOVERY_HOSTNAME"] == "stub-host"
    # The loki sink joins endpoint + "/" + path.
    assert env["DISCOVERY_LOKI_ENDPOINT"] == "http://loki:3100/loki/api/v1"
    assert env["DISCOVERY_LOKI_PATH"] == "push"
    assert env["VECTOR_CONFIG"] == str(vc.CONFIG)
    assert _vector_args(result) == [INTERPOLATION_FLAG, "validate"]


def test_entrypoint_sets_every_interpolated_variable(tmp_path: Path) -> None:
    # Vector fails on an unset ${NAME} only when interpolation is on, and
    # the entrypoint must leave none unset in either vector_check run.
    text = vc.CONFIG.read_text(encoding="utf-8")
    wanted = vc.interpolations(text) | vc.env_reads(text)
    for run, env in nx.VECTOR_CHECK_ENVS.items():
        seen = _vector_env(_run_entrypoint(_stub_bin(tmp_path / run), env))
        assert all(seen.get(name) for name in wanted), wanted - set(seen)


def test_entrypoint_keeps_given_values(tmp_path: Path) -> None:
    env = _vector_env(
        _run_entrypoint(
            _stub_bin(tmp_path),
            {
                "RU_3OPS_DISCOVERY_DOCKER_HOST": "tcp://proxy:2375",
                "RU_3OPS_DISCOVERY_HOSTNAME": "node-1",
                "RU_3OPS_DISCOVERY_LOKI_PUSH_URL": (
                    "http://victorialogs:9428/insert/loki/api/v1/push"
                ),
            },
        )
    )
    assert env["RU_3OPS_DISCOVERY_DOCKER_HOST"] == "tcp://proxy:2375"
    assert env["RU_3OPS_DISCOVERY_HOSTNAME"] == "node-1"
    assert env["DISCOVERY_LOKI_ENDPOINT"] == (
        "http://victorialogs:9428/insert/loki/api/v1"
    )
    assert env["DISCOVERY_LOKI_PATH"] == "push"


@pytest.mark.parametrize("name", sorted(LOGS_ENV))
def test_entrypoint_rejects_a_newline(tmp_path: Path, name: str) -> None:
    result = _run_entrypoint(_stub_bin(tmp_path), {name: "a\nb: c"})
    assert result.returncode == 1
    assert name in result.stderr
    assert "newline" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://loki:3100", "needs a path"),
        ("http://loki:3100/loki/api/v1/push/", "needs a path"),
        (
            "http://vl:9428/insert/loki/api/v1/push?_stream_fields=a/b",
            "query or fragment",
        ),
        ("http://vl:9428/insert/loki/api/v1/push?x=1", "query or fragment"),
        ("http://loki:3100/loki/api/v1/push#frag", "query or fragment"),
    ],
)
def test_entrypoint_rejects_a_push_url_it_cannot_split(
    tmp_path: Path, url: str, reason: str
) -> None:
    result = _run_entrypoint(
        _stub_bin(tmp_path), {"RU_3OPS_DISCOVERY_LOKI_PUSH_URL": url}
    )
    assert result.returncode == 1
    assert "RU_3OPS_DISCOVERY_LOKI_PUSH_URL" in result.stderr
    assert reason in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("hostname", ["exit 1", "echo"])
def test_entrypoint_rejects_a_missing_hostname(
    tmp_path: Path, hostname: str
) -> None:
    result = _run_entrypoint(_stub_bin(tmp_path, hostname), {})
    assert result.returncode == 1
    assert "hostname" in result.stderr
    assert result.stdout == ""


def test_entrypoint_execs_vector_with_interpolation() -> None:
    # Without the flag Vector keeps ${NAME} as literal text and validate
    # still passes, so vector_check alone would not notice its loss.
    text = vc.ENTRYPOINT.read_text(encoding="utf-8")
    assert f'exec vector {INTERPOLATION_FLAG} "$@"' in text


# --- Registry, pin and the nox gate ---


def test_vector_pin_matches_registry() -> None:
    version = nx.VECTOR_IMAGE.split(":")[1].removesuffix("-alpine")
    assert f"timberio/vector:{version}-alpine" == nx.VECTOR_IMAGE
    assert md.implementation_agent("vector") == f"Vector {version}"


def test_e2e_overlay_vector_image_matches_pin() -> None:
    # vector_check and the e2e overlay must run the same pinned tag.
    overlay = nx.REPO / "tests/e2e/stack/docker-compose.vector.yml"
    images = set(
        re.findall(r"timberio/vector:[\w.-]+", overlay.read_text("utf-8"))
    )
    assert images == {nx.VECTOR_IMAGE}


def test_e2e_overlay_tmpfs_is_the_configured_data_dir() -> None:
    """
    Pins: the overlay's tmpfs path equals the config's data_dir.

    Otherwise the tmpfs is unused.
    """
    overlay = yaml.safe_load(
        (nx.REPO / "tests/e2e/stack/docker-compose.vector.yml").read_text(
            "utf-8"
        )
    )
    assert overlay["services"]["vector"]["tmpfs"] == [_config()["data_dir"]]


def test_registry_lists_vector_for_logs_only() -> None:
    assert md.implementations()["vector"] == {"logs"}


def test_vector_check_runs_through_the_entrypoint_both_ways() -> None:
    # One run proves the 14.1 defaults alone yield a loadable config, the
    # other the e2e values: tcp:// docker host, empty hostname and a push
    # URL with a longer path.
    assert nx.VECTOR_CHECK_ENVS["defaults"] == {}
    assert set(nx.VECTOR_CHECK_ENVS["e2e"]) == LOGS_ENV
    assert nx.VECTOR_CHECK_ENVS["e2e"]["RU_3OPS_DISCOVERY_HOSTNAME"] == ""


def test_vector_check_args_are_the_exact_docker_run_command() -> None:
    """Pins every flag: a changed literal runs a different command."""
    assert nx.vector_check_args({"A": "b", "C": ""}) == [
        "docker",
        "run",
        "--rm",
        "-e",
        "A=b",
        "-e",
        "C=",
        "-v",
        f"{nx.VECTOR_DIR}:/etc/vector:ro",
        "--entrypoint",
        "/bin/sh",
        nx.VECTOR_IMAGE,
        "/etc/vector/entrypoint.sh",
        "validate",
        "--no-environment",
        "--deny-warnings",
    ]


def test_vector_check_is_a_default_gate() -> None:
    assert "vector_check" in (nox.options.sessions or [])


# --- Extractor error paths ---


def test_load_rejects_a_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("- a\n", encoding="utf-8")
    with pytest.raises(vc.VectorConfigError, match="not a YAML mapping"):
        vc.load_vector_config(path)


def test_components_reject_a_reused_id() -> None:
    config: dict[str, Any] = {"sources": {"a": {}}, "sinks": {"a": {}}}
    with pytest.raises(vc.VectorConfigError, match="a reused"):
        vc.components(config)


@pytest.mark.parametrize("kind", ["remap", "filter", "route"])
def test_components_reject_vrl_from_a_file(kind: str) -> None:
    """Pins the gates' reach: VRL in a file is invisible to every scan."""
    config: dict[str, Any] = {
        "transforms": {"t": {"type": kind, "file": "/etc/vector/x.vrl"}}
    }
    with pytest.raises(
        vc.VectorConfigError, match=r"^t: VRL in a file is invisible"
    ):
        vc.components(config)


def test_remap_sources_need_a_source() -> None:
    """Pins a named error for a remap without its program."""
    config: dict[str, Any] = {"transforms": {"t": {"type": "remap"}}}
    with pytest.raises(
        vc.VectorConfigError, match=r"^t: remap has no source$"
    ):
        vc.remap_sources(config)


def test_an_input_naming_no_component_is_an_error() -> None:
    config: dict[str, Any] = {"transforms": {"t": {"inputs": ["ghost.out"]}}}
    with pytest.raises(vc.VectorConfigError, match=r"ghost\.out names no"):
        vc.upstream("t", config)


def test_sink_template_must_be_one_field() -> None:
    config = _config()
    sink = config["sinks"][vc.logs_sink(config)[0]]
    sink["structured_metadata"] = {"*": "{{ a }}-{{ b }}"}
    with pytest.raises(vc.VectorConfigError, match="not one field"):
        vc.sink_metadata_field(config)


def test_profile_branch_needs_exactly_one_consumer() -> None:
    config = _config()
    route, _ = vc.profile_route(config)
    config["sinks"][vc.logs_sink(config)[0]]["inputs"].append(
        f"{route}.generic-json-v1"
    )
    with pytest.raises(vc.VectorConfigError, match="2 consumers"):
        vc.profile_branches(config)


# --- Extractors on synthetic configs ---


def _loki_sink(**extra: Any) -> dict[str, Any]:
    return {
        "type": "loki",
        "inputs": [],
        "labels": {"*": "{{ out }}"},
        "structured_metadata": {"*": "{{ meta }}"},
        **extra,
    }


def _mini(source: str, **transforms: dict[str, Any]) -> dict[str, Any]:
    """Return a config whose only label writer runs ``source``."""
    return {
        "sinks": {"sink": _loki_sink()},
        "transforms": {
            "w": {"type": "remap", "inputs": [], "source": source},
            **transforms,
        },
    }


def _renamed_field_config() -> dict[str, Any]:
    """Return the real config with the labels event field renamed."""
    config = _config()
    writer = _writer(config)
    writer["source"] = writer["source"].replace(
        ".stream_labels = indexed", ".labels_out = indexed"
    )
    config["sinks"][vc.logs_sink(config)[0]]["labels"] = {
        "*": "{{ labels_out }}"
    }
    return config


def test_upstream_resolves_inputs_in_the_given_config() -> None:
    config: dict[str, Any] = {
        "sources": {"a": {}},
        "transforms": {"t": {"inputs": ["a"]}, "u": {"inputs": ["t.out"]}},
    }
    assert vc.upstream("u", config) == {"t", "a"}


def test_an_input_resolves_to_its_first_dotted_segment() -> None:
    config: dict[str, Any] = {
        "sources": {"a": {}},
        "transforms": {"t": {"inputs": ["a"]}, "u": {"inputs": ["t.x.y"]}},
    }
    assert vc.upstream("u", config) == {"t", "a"}


@pytest.mark.parametrize(
    ("extractor", "what"),
    [
        (vc.sink_label_field, "labels"),
        (vc.sink_metadata_field, "structured_metadata"),
    ],
)
def test_sink_template_errors_name_the_template(
    extractor: Any, what: str
) -> None:
    config = _config()
    sink = config["sinks"][vc.logs_sink(config)[0]]
    sink[what] = {"a": "{{ x }}"}
    with pytest.raises(
        vc.VectorConfigError, match=f"^sink {what} is not one '\\*' template$"
    ):
        extractor(config)


def test_label_writer_follows_the_sink_field_of_the_given_config() -> None:
    config = _renamed_field_config()
    assert (
        vc.stream_labels_writer(config)[0]
        == (vc.stream_labels_writer(_config())[0])
    )
    assert vc.stream_label_problems(config) == []


def test_label_keys_come_from_the_given_config() -> None:
    config = _renamed_field_config()
    writer = _writer(config)
    writer["source"] = writer["source"].replace(
        '"source": "docker"', '"source": "docker", "extra": "x"'
    )
    writer["source"] += "indexed.added = 1\n"
    assert vc.static_stream_labels(config)["extra"] == "x"
    keys = vc.stream_label_keys(config)
    assert {"extra", "added"} <= keys


def test_static_labels_need_an_initial_literal() -> None:
    config = _mini("indexed = make()\n.out = indexed\n")
    with pytest.raises(
        vc.VectorConfigError, match=r"^indexed has no initial object literal$"
    ):
        vc.static_stream_labels(config)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"type": "reduce"}, True),
        ({"type": "remap", "source": "x = .message"}, True),
        ({"type": "remap", "source": "x = parse_json!(y)"}, True),
        ({"type": "remap", "source": "x = 1"}, False),
        ({"type": "remap", "inputs": ["parse_a"], "source": "x = 1"}, False),
        ({"type": "remap", "_kind": ".message", "source": "x = 1"}, False),
    ],
)
def test_a_component_reads_the_line_when_it_mentions_it(
    body: dict[str, Any], expected: bool
) -> None:
    assert vc._reads_message(body) is expected


def test_label_gate_names_a_writer_that_mentions_a_parser() -> None:
    config = _config()
    name = vc.stream_labels_writer(config)[0]
    _writer(config)["source"] += "unused = parse_json!(y)\n"
    assert f"{name} reads line content" in vc.stream_label_problems(config)


@pytest.mark.parametrize(
    "line",
    [
        "indexed.k = indexed",
        "indexed = {indexed}",
        "indexed.k = 1; indexed = foo",
    ],
)
def test_label_gate_names_a_label_variable_changed_otherwise(
    line: str,
) -> None:
    config = _config()
    name = vc.stream_labels_writer(config)[0]
    source = _writer(config)["source"]
    _writer(config)["source"] = source.replace(
        ".stream_labels = indexed", f"{line}\n.stream_labels = indexed"
    )
    assert f"{name}: indexed is changed other than key by key" in (
        vc.stream_label_problems(config)
    )


def test_label_gate_names_a_second_initial_literal() -> None:
    config = _config()
    name = vc.stream_labels_writer(config)[0]
    _writer(config)["source"] = "indexed = {}\n" + _writer(config)["source"]
    assert f"{name}: indexed needs exactly one initial literal" in (
        vc.stream_label_problems(config)
    )


def test_label_gate_flags_a_parallel_parser() -> None:
    config = _config()
    name = vc.stream_labels_writer(config)[0]
    writer_input = _writer(config)["inputs"]
    parser = next(
        key
        for key, body in config["transforms"].items()
        if vc.parser_kind(body) == "json"
    )
    config["transforms"][parser]["inputs"] = list(writer_input)
    assert f"{parser} reads line content without {name} upstream" in (
        vc.stream_label_problems(config)
    )


def test_label_gate_ignores_a_sink_that_mentions_the_line() -> None:
    config = _config()
    sink = config["sinks"][vc.logs_sink(config)[0]]
    sink["encoding"] = {"message": ".message", "parse": "parse_x"}
    assert vc.stream_label_problems(config) == []


def test_list_assignment_names_the_missing_variable() -> None:
    config = _mini("indexed = {}\n.out = indexed\n")
    with pytest.raises(
        vc.VectorConfigError, match=r"^no list literal assigned to profiles$"
    ):
        vc.profile_allowlist(config)


def test_unknown_profile_branch_is_required() -> None:
    config = _mini("indexed = {}\n.out = indexed\n")
    with pytest.raises(
        vc.VectorConfigError, match=r"^no unknown-profile branch$"
    ):
        vc.unknown_profile_branch(config)


def test_profile_route_conditions_must_be_strings() -> None:
    config = _config()
    route = vc.profile_route(config)[0]
    config["transforms"][route]["route"]["raw"] = {"type": "vrl"}
    with pytest.raises(
        vc.VectorConfigError, match=f"^{route}: route conditions must be str"
    ):
        vc.profile_route(config)


def test_parser_kind_ignores_a_body_without_source_or_remap() -> None:
    assert vc.parser_kind({"type": "remap"}) is None
    foreign = {
        "type": "filter",
        "source": 'parse_json(string(.message) ?? "")',
    }
    assert vc.parser_kind(foreign) is None


def test_logfmt_grammar_needs_one_remap() -> None:
    with pytest.raises(vc.VectorConfigError, match=r"^0 logfmt remaps$"):
        vc.logfmt_grammar({"transforms": {}})


_PREFIX_CALL = "p = parse_regex(string(.message) ?? \"\", r'{prefix}')\n"
_PAIRS_CALL = "q = parse_regex_all(p, r'{pairs}')\n"


def test_logfmt_grammar_needs_both_regexes() -> None:
    config: dict[str, Any] = {
        "transforms": {
            "t": {
                "type": "remap",
                "source": _PREFIX_CALL.format(prefix="^a"),
            }
        }
    }
    with pytest.raises(
        vc.VectorConfigError, match=r"^logfmt remap lacks its two regexes$"
    ):
        vc.logfmt_grammar(config)


def test_logfmt_grammar_needs_the_prefix_regex() -> None:
    """Pins the pair: a pair regex alone is no logfmt grammar either."""
    config: dict[str, Any] = {
        "transforms": {
            "t": {
                "type": "remap",
                "source": "x = parse_regex(string(.message), r'^a')\n"
                + _PAIRS_CALL.format(pairs="b"),
            }
        }
    }
    with pytest.raises(
        vc.VectorConfigError, match=r"^logfmt remap lacks its two regexes$"
    ):
        vc.logfmt_grammar(config)


def test_logfmt_grammar_reads_both_regexes() -> None:
    """Pins which regex is which when both are present."""
    config: dict[str, Any] = {
        "transforms": {
            "t": {
                "type": "remap",
                "source": _PREFIX_CALL.format(prefix="^a")
                + _PAIRS_CALL.format(pairs="b"),
            }
        }
    }
    assert vc.logfmt_grammar(config) == ("^a", "b")


def test_logfmt_grammar_unescapes_both_regexes() -> None:
    config: dict[str, Any] = {
        "transforms": {
            "t": {
                "type": "remap",
                "source": _PREFIX_CALL.format(prefix="^a$$")
                + _PAIRS_CALL.format(pairs="b$$"),
            }
        }
    }
    assert vc.logfmt_grammar(config) == ("^a$", "b$")


def test_profile_branches_read_the_given_config() -> None:
    config: dict[str, Any] = {
        "transforms": {
            "r": {
                "type": "route",
                "inputs": [],
                "route": {
                    "o": '.stream_labels.log_profile == "p1"',
                    "n": '.stream_labels.log_profile == "p2"',
                },
            },
            "parse": {
                "type": "remap",
                "inputs": ["r.o"],
                "source": 'fields = ["a", "b"]\n'
                'x = parse_json(string(.message) ?? "")\n',
            },
            "pass": {"type": "filter", "inputs": ["r.n"]},
        }
    }
    assert vc.profile_branches(config) == {
        "p1": {"o": ("json", {"a", "b"})},
        "p2": {"n": (None, set())},
    }


def _optout_config(consumer: dict[str, Any]) -> dict[str, Any]:
    return {
        "sources": {"src": {"type": "docker_logs"}},
        "transforms": {"f": {"inputs": ["src"], **consumer}},
    }


def test_optout_condition_reads_the_given_config() -> None:
    config = _optout_config({"type": "filter", "condition": ".x"})
    assert vc.optout_condition(config) == ".x"


def test_optout_source_must_feed_a_filter() -> None:
    config = _optout_config({"type": "remap", "condition": ".x"})
    with pytest.raises(vc.VectorConfigError, match=r"not one filter$"):
        vc.optout_condition(config)


def test_optout_condition_must_be_a_vrl_string() -> None:
    config = _optout_config({"type": "filter", "condition": {"a": 1}})
    with pytest.raises(
        vc.VectorConfigError, match=r"^opt-out condition is not a VRL string$"
    ):
        vc.optout_condition(config)


def _reduce_config(**body: Any) -> dict[str, Any]:
    return {"transforms": {"m": {"type": "reduce", **body}}}


def test_multiline_without_inputs_has_an_empty_set() -> None:
    config = _reduce_config(starts_when="match(.message, r'^x')")
    assert vc.multiline(config)["inputs"] == set()


def test_multiline_start_needs_a_raw_regex() -> None:
    config = _reduce_config(starts_when="starts_with(.message, 'x')")
    with pytest.raises(
        vc.VectorConfigError, match=r"^m: starts_when has no raw regex$"
    ):
        vc.multiline(config)


def test_multiline_start_must_be_a_vrl_condition() -> None:
    config = _reduce_config(starts_when=5)
    with pytest.raises(
        vc.VectorConfigError, match=r"^not a VRL condition: 5$"
    ):
        vc.multiline(config)
