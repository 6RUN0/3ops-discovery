"""
Structured reading of the Vector implementation (implementations/vector/).

``vector.yaml`` is plain YAML, so the component graph is parsed rather
than scanned; VRL programs inside it are read by regex, and only for the
few facts the gates compare against the manifest. ``entrypoint.sh`` is
POSIX sh; the facts taken from it are its ``${NAME:-default}``
expansions, and the tests also run it with a stub ``vector`` binary.

Every extractor takes an optional parsed config, so a test can hand it a
broken copy and check that the gate rejects it.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
VECTOR_DIR = REPO / "implementations" / "vector"
CONFIG = VECTOR_DIR / "vector.yaml"
ENTRYPOINT = VECTOR_DIR / "entrypoint.sh"

#: Event field the sink turns into stream labels, and the one it turns
#: into structured metadata (both via a whole-object "*" template).
STREAM_LABELS_FIELD = "stream_labels"
STRUCTURED_METADATA_FIELD = "structured_metadata"

_DEFAULT_EXPANSION = re.compile(r"\$\{(RU_3OPS_DISCOVERY_\w+):-([^}]*)\}")
#: Vector's interpolation forms: ${NAME}, ${NAME:-x}, ${NAME-x}, $NAME.
_INTERPOLATION = re.compile(r"\$\{(\w+)(?::?-[^}]*)?\}|\$(\w+)")
_ESCAPED_DOLLAR = "$$"
_BRACED = re.compile(r"\$\{\w+\}")
_ENV_READ = re.compile(r'get_env_var!?\("(\w+)"\)')
_WHOLE_OBJECT = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_PROFILE_CONDITION = re.compile(
    r"^\." + STREAM_LABELS_FIELD + r'\.log_profile == "([\w-]+)"'
)
_LIST_LITERAL = re.compile(r'"([^"]+)"')
#: `. = x`, `. |= x`, and the root as the first argument of a function
#: that rewrites it (set!, merge, remove, del).
_ROOT_WRITE = re.compile(
    r"(?m)^\s*\.\s*\|?=[^=]|\b(?:set|merge|remove|del)!?\(\s*\.\s*[,)]"
)
_MESSAGE_PARSE = re.compile(r"\b(parse_\w+)\(string\(\.message\)")
_MESSAGE_PARSERS = {"parse_json": "json", "parse_regex": "logfmt"}

#: Parsed vector.yaml; ``None`` means the real file.
Config = dict[str, Any] | None


class VectorConfigError(AssertionError):
    """The Vector config does not have the shape the gates expect."""


def load_vector_config(path: Path) -> dict[str, Any]:
    """Return the parsed Vector config at ``path``."""
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise VectorConfigError(f"{path} is not a YAML mapping")
    return parsed


@cache
def _real() -> dict[str, Any]:
    return load_vector_config(CONFIG)


def _config(config: Config) -> dict[str, Any]:
    return _real() if config is None else config


def components(config: Config = None) -> dict[str, dict[str, Any]]:
    """Return every source, transform and sink by component id."""
    found: dict[str, dict[str, Any]] = {}
    for kind in ("sources", "transforms", "sinks"):
        for name, body in (_config(config).get(kind) or {}).items():
            if name in found:
                raise VectorConfigError(f"component id {name} reused")
            found[name] = {**body, "_kind": kind}
    return found


def _component_of(output: str, config: Config) -> str:
    """Map an input reference (``id`` or ``id.output``) to its component."""
    known = components(config)
    if output in known:
        return output
    head = output.split(".", 1)[0]
    if head not in known:
        raise VectorConfigError(f"input {output} names no component")
    return head


def consumers(output: str, config: Config = None) -> list[str]:
    """Return the components that list ``output`` among their inputs."""
    return sorted(
        name
        for name, body in components(config).items()
        if output in body.get("inputs", [])
    )


def upstream(name: str, config: Config = None) -> set[str]:
    """Return every component that feeds ``name``, directly or not."""
    known = components(config)
    seen: set[str] = set()
    pending = [name]
    while pending:
        for output in known[pending.pop()].get("inputs", []):
            parent = _component_of(output, config)
            if parent not in seen:
                seen.add(parent)
                pending.append(parent)
    return seen


def _one_of_type(
    kind: str, type_: str, config: Config
) -> tuple[str, dict[str, Any]]:
    matches = [
        (name, body)
        for name, body in components(config).items()
        if body["_kind"] == kind and body.get("type") == type_
    ]
    if len(matches) != 1:
        raise VectorConfigError(f"{len(matches)} {type_} {kind}")
    return matches[0]


def logs_sink(config: Config = None) -> tuple[str, dict[str, Any]]:
    """Return the single loki sink."""
    return _one_of_type("sinks", "loki", config)


def _whole_object_field(mapping: Any, what: str) -> str:
    """Return X when ``mapping`` is exactly ``{"*": "{{ X }}"}``."""
    if not isinstance(mapping, dict) or set(mapping) != {"*"}:
        raise VectorConfigError(f"sink {what} is not one '*' template")
    match = _WHOLE_OBJECT.fullmatch(str(mapping["*"]).strip())
    if match is None:
        raise VectorConfigError(f"sink {what} template is not one field")
    return match.group(1)


def sink_label_field(config: Config = None) -> str:
    """Return the event field the sink expands into stream labels."""
    return _whole_object_field(logs_sink(config)[1].get("labels"), "labels")


def sink_metadata_field(config: Config = None) -> str:
    """Return the event field the sink expands into structured metadata."""
    return _whole_object_field(
        logs_sink(config)[1].get("structured_metadata"), "structured_metadata"
    )


def remap_sources(config: Config = None) -> dict[str, str]:
    """Return remap transform id -> its VRL program."""
    return {
        name: body["source"]
        for name, body in components(config).items()
        if body.get("type") == "remap"
    }


def _writes_field(source: str, field: str) -> re.Match[str] | None:
    return re.search(rf"(?m)^\s*\.{field}\s*=\s*(\S+)\s*$", source)


def stream_labels_writer(config: Config = None) -> tuple[str, str, str]:
    """
    Return (transform id, VRL program, local variable) of the label writer.

    Exactly one remap may assign the stream labels field, and it must
    assign a local variable the program builds key by key.
    """
    field = sink_label_field(config)
    writers = [
        (name, source, match.group(1))
        for name, source in remap_sources(config).items()
        if (match := _writes_field(source, field))
    ]
    if len(writers) != 1:
        raise VectorConfigError(f"{len(writers)} transforms write .{field}")
    return writers[0]


def static_stream_labels(config: Config = None) -> dict[str, str]:
    """Return the constant labels of the writer's initial object literal."""
    _, source, var = stream_labels_writer(config)
    literal = re.search(rf"(?m)^\s*{var} = \{{(.*)\}}\s*$", source)
    if literal is None:
        raise VectorConfigError(f"{var} has no initial object literal")
    return dict(re.findall(r'"(\w+)":\s*"([^"]*)"', literal.group(1)))


def stream_label_keys(config: Config = None) -> set[str]:
    """Return every stream label name the writer can emit."""
    _, source, var = stream_labels_writer(config)
    assigned = set(re.findall(rf"\b{var}\.(\w+)\s*=", source))
    return set(static_stream_labels(config)) | assigned


def _reads_message(body: dict[str, Any]) -> bool:
    if body.get("type") == "reduce":
        return True
    text = yaml.safe_dump(
        {k: v for k, v in body.items() if k not in ("inputs", "_kind")}
    )
    return ".message" in text or "parse_" in text


def stream_label_problems(config: Config = None) -> list[str]:
    """
    Return why stream labels could carry line content (empty: they cannot).

    The writer must read no line content itself, must not sit downstream
    of anything that reads it, and every component that reads it must
    sit downstream of the writer, so no parser output can reach a label.
    """
    name, source, var = stream_labels_writer(config)
    field = sink_label_field(config)
    problems = []
    if ".message" in source or "parse_" in source:
        problems.append(f"{name} reads line content")
    problems.extend(_writer_variable_problems(name, source, var, field))
    known = components(config)
    # Any other mention can write: assignment, merge, |=, field set, del,
    # a quoted path or a set!() path array naming the field.
    problems.extend(
        f"{other} touches .{field}"
        for other, body in sorted(known.items())
        if other != name
        and (
            re.search(rf'\.{field}\b|"{field}"', body.get("source", ""))
            or field in (body.get("merge_strategies") or {})
        )
    )
    # A write to the event root can replace or merge the field whole.
    problems.extend(
        f"{other} writes the event root"
        for other, body in sorted(known.items())
        if other != name and _ROOT_WRITE.search(body.get("source", ""))
    )
    before = upstream(name, config)
    problems.extend(
        f"{other} reads line content before {name}"
        for other in sorted(before)
        if _reads_message(known[other])
    )
    problems.extend(
        f"{other} reads line content without {name} upstream"
        for other, body in sorted(known.items())
        if other != name
        and body["_kind"] == "transforms"
        and _reads_message(body)
        and name not in upstream(other, config)
    )
    return problems


def _writer_variable_problems(
    name: str, source: str, var: str, field: str
) -> list[str]:
    """
    Return why the writer's label variable may hold more than its keys.

    Allowed: one initial object literal, ``var.key = ...`` assignments
    and the final ``.field = var``. Anything else (``merge``, ``|=``,
    reassignment, ``del``) could add keys ``stream_label_keys`` misses.
    """
    problems = []
    init = re.compile(rf"(?m)^\s*{var} = \{{")
    if len(init.findall(source)) != 1:
        problems.append(f"{name}: {var} needs exactly one initial literal")
    rest = init.sub("", source)
    rest = re.sub(rf"\b{var}\.\w+ = ", "", rest)
    rest = re.sub(rf"(?m)^\s*\.{field} = {var}\s*$", "", rest)
    if re.search(rf"\b{var}\b", rest):
        problems.append(f"{name}: {var} is changed other than key by key")
    return problems


def _list_assignment(source: str, var: str) -> list[str]:
    match = re.search(rf"(?m)^\s*{var} = \[(.*)\]\s*$", source)
    if match is None:
        raise VectorConfigError(f"no list literal assigned to {var}")
    return _LIST_LITERAL.findall(match.group(1))


def profile_allowlist(config: Config = None) -> list[str]:
    """Return the ``profiles`` list literal of the label writer."""
    return _list_assignment(stream_labels_writer(config)[1], "profiles")


def unknown_profile_branch(config: Config = None) -> str:
    """Return the body of the ``if !includes(profiles, ...)`` block."""
    source = stream_labels_writer(config)[1]
    match = re.search(
        r"(?ms)^(\s*)if !includes\(profiles, (\w+)\) \{\n(.*?)^\1\}", source
    )
    if match is None:
        raise VectorConfigError("no unknown-profile branch")
    return match.group(3)


def fallback_profile(config: Config = None) -> str:
    """Return the profile the unknown-profile branch assigns."""
    body = unknown_profile_branch(config)
    found = re.findall(r'(?m)^\s*\w+ = "([\w-]+)"\s*$', body)
    if len(found) != 1:
        raise VectorConfigError(f"{len(found)} fallback assignments")
    return str(found[0])


def profile_route(config: Config = None) -> tuple[str, dict[str, str]]:
    """Return (route id, output -> VRL condition) of the profile route."""
    name, body = _one_of_type("transforms", "route", config)
    routes = body.get("route") or {}
    if not all(isinstance(c, str) for c in routes.values()):
        raise VectorConfigError(f"{name}: route conditions must be strings")
    return name, dict(routes)


def routed_profiles(config: Config = None) -> dict[str, str]:
    """Return route output -> the profile its condition selects."""
    found = {}
    for output, condition in profile_route(config)[1].items():
        match = _PROFILE_CONDITION.match(condition)
        if match is None:
            raise VectorConfigError(f"{output}: condition names no profile")
        found[output] = match.group(1)
    return found


def parser_kind(body: dict[str, Any]) -> str | None:
    """
    Return ``json`` or ``logfmt`` for a parsing remap, else ``None``.

    The kind is the VRL function applied to the line itself. logfmt is
    ``parse_regex`` over the go-logfmt grammar (``logfmt_grammar``):
    ``parse_logfmt`` and ``parse_key_value`` disagree with the reference
    on empty values, standalone keys, duplicates and malformed pairs.
    """
    source = body.get("source", "") if body.get("type") == "remap" else ""
    calls = set(_MESSAGE_PARSE.findall(source))
    unknown = calls - set(_MESSAGE_PARSERS)
    if unknown:
        raise VectorConfigError(f"line parsed with {sorted(unknown)}")
    kinds = {_MESSAGE_PARSERS[call] for call in calls}
    if len(kinds) > 1:
        raise VectorConfigError(f"one remap runs two parsers: {kinds}")
    return kinds.pop() if kinds else None


def logfmt_grammar(config: Config = None) -> tuple[str, str]:
    """
    Return (valid-prefix regex, pair regex) of the logfmt remap.

    Both as Vector sees them after interpolation (``$$`` is ``$``), so a
    test can run them on the reference's edge cases.
    """
    sources = [
        body["source"]
        for body in components(config).values()
        if parser_kind(body) == "logfmt"
    ]
    if len(sources) != 1:
        raise VectorConfigError(f"{len(sources)} logfmt remaps")
    prefix = re.search(
        r"parse_regex\(string\(\.message\) \?\? \"\", r'([^']*)'\)",
        sources[0],
    )
    pairs = re.search(r"parse_regex_all\([^,]*, r'([^']*)'\)", sources[0])
    if prefix is None or pairs is None:
        raise VectorConfigError("logfmt remap lacks its two regexes")
    return (
        prefix.group(1).replace(_ESCAPED_DOLLAR, "$"),
        pairs.group(1).replace(_ESCAPED_DOLLAR, "$"),
    )


def profile_branches(
    config: Config = None,
) -> dict[str, dict[str, tuple[str | None, set[str]]]]:
    """
    Return profile -> route output -> (parser kind, extracted fields).

    The fields are the ``fields`` list literal of the parsing remap that
    consumes the output; a non-parsing consumer extracts nothing.
    """
    route, _ = profile_route(config)
    known = components(config)
    found: dict[str, dict[str, tuple[str | None, set[str]]]] = {}
    for output, profile in routed_profiles(config).items():
        takers = consumers(f"{route}.{output}", config)
        if len(takers) != 1:
            raise VectorConfigError(f"{output}: {len(takers)} consumers")
        body = known[takers[0]]
        kind = parser_kind(body)
        fields = (
            set(_list_assignment(body["source"], "fields")) if kind else set()
        )
        found.setdefault(profile, {})[output] = (kind, fields)
    return found


def optout_condition(config: Config = None) -> str:
    """
    Return the VRL condition of the filter right after the docker source.

    The docker_logs source must feed that filter and nothing else, so no
    path to the sink bypasses the opt-out.
    """
    source, _ = _one_of_type("sources", "docker_logs", config)
    takers = consumers(source, config)
    known = components(config)
    if len(takers) != 1 or known[takers[0]].get("type") != "filter":
        raise VectorConfigError(f"{source} feeds {takers}, not one filter")
    condition = known[takers[0]].get("condition")
    if not isinstance(condition, str):
        raise VectorConfigError("opt-out condition is not a VRL string")
    return condition


def _vrl(condition: Any) -> str:
    if isinstance(condition, str):
        return condition
    if isinstance(condition, dict) and condition.get("type") == "vrl":
        return str(condition["source"])
    raise VectorConfigError(f"not a VRL condition: {condition!r}")


def multiline(config: Config = None) -> dict[str, Any]:
    """Return the parameters of the single reduce transform."""
    name, body = _one_of_type("transforms", "reduce", config)
    if "ends_when" in body:
        raise VectorConfigError(f"{name}: ends_when splits blocks too")
    anchor = re.search(r"r'([^']*)'", _vrl(body.get("starts_when")))
    if anchor is None:
        raise VectorConfigError(f"{name}: starts_when has no raw regex")
    return {
        "inputs": set(body.get("inputs", [])),
        "group_by": body.get("group_by"),
        "anchor": anchor.group(1),
        "max_events": body.get("max_events"),
        "expire_after_ms": body.get("expire_after_ms"),
        "merge_strategies": body.get("merge_strategies"),
    }


def interpolations(text: str) -> set[str]:
    """Return every environment variable ``text`` interpolates."""
    unescaped = text.replace(_ESCAPED_DOLLAR, "")
    return {a or b for a, b in _INTERPOLATION.findall(unescaped)}


def bare_dollars(text: str) -> list[str]:
    """
    Return the lines holding a ``$`` that is neither ``$$`` nor ``${NAME}``.

    With interpolation on, Vector expands ``$NAME`` anywhere in the file,
    VRL included, so a regex anchor ``$`` must be written ``$$``.
    """
    return [
        line
        for line in text.splitlines()
        if "$" in _BRACED.sub("", line.replace(_ESCAPED_DOLLAR, ""))
    ]


def defaulted_interpolations(text: str) -> set[str]:
    """Return the variables ``text`` interpolates with an inline default."""
    unescaped = text.replace(_ESCAPED_DOLLAR, "")
    return set(re.findall(r"\$\{(\w+):?-", unescaped))


def env_reads(text: str) -> set[str]:
    """Return the variables VRL reads at runtime with ``get_env_var``."""
    return set(_ENV_READ.findall(text))


def entrypoint_defaults(text: str | None = None) -> dict[str, str]:
    """Return env name -> default from ``entrypoint.sh`` expansions."""
    if text is None:
        text = ENTRYPOINT.read_text(encoding="utf-8")
    defaults: dict[str, str] = {}
    for name, default in _DEFAULT_EXPANSION.findall(text):
        if defaults.setdefault(name, default) != default:
            raise VectorConfigError(f"{name} has diverging defaults")
    if not defaults:
        raise VectorConfigError(f"no ${{NAME:-default}} in {ENTRYPOINT}")
    return defaults
