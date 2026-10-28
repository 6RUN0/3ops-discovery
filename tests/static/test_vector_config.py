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
    json_anchor = "match(string(.message) ?? \"\", r'^\\s*\\{')"
    assert json_anchor in routes["mixed-v1-json"]
    assert f"!{json_anchor}" in routes["mixed-v1-logfmt"]
    assert f"!{json_anchor}" not in routes["mixed-v1-json"]
    assert "(^|\\s)(level|msg|status)=" in routes["mixed-v1-logfmt"]


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
    # River escapes each backslash; the VRL raw string does not.
    assert params["anchor"] == reference["firstline"].replace("\\\\", "\\")
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
