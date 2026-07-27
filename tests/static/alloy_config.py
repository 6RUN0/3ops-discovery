"""
Regex-level scanning of the reference *.alloy sources.

Deliberately shallow: the scanner extracts the handful of normative
facts the static gates compare against the manifest. It is
NOT an Alloy parser; every extraction is pinned to the real files by
tests/static/test_alloy_config.py, so a config refactor that breaks an
assumption fails loudly there.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALLOY_DIR = REPO / "alloy"
OPTIONAL_DIR = REPO / "alloy-optional"

_LABEL = "__meta_docker_container_label_ru_3ops_discovery"

_COMPONENT_DECL = re.compile(r'(?m)^([a-z][\w.]+)\s+"([^"]+)"\s*\{')


@cache
def sources() -> dict[str, str]:
    """Return {file name: text} for every base config file."""
    files = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(ALLOY_DIR.glob("*.alloy"))
    }
    if not files:
        raise FileNotFoundError(f"no *.alloy files in {ALLOY_DIR}")
    return files


@cache
def optional_sources() -> dict[str, str]:
    """Return {file name: text} for every optional overlay file."""
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(OPTIONAL_DIR.glob("*.alloy"))
    }


def _component_names(text: str) -> set[str]:
    """Every "type.label" component declared in a config text."""
    return {f"{typ}.{label}" for typ, label in _COMPONENT_DECL.findall(text)}


def base_component_names() -> set[str]:
    names: set[str] = set()
    for text in sources().values():
        names |= _component_names(text)
    return names


def optional_component_names() -> set[str]:
    names: set[str] = set()
    for text in optional_sources().values():
        names |= _component_names(text)
    return names


def optional_component_names_by_file() -> dict[str, set[str]]:
    """Per-overlay component name sets (for pairwise collision gates)."""
    return {
        name: _component_names(text)
        for name, text in optional_sources().items()
    }


def extension_point_targets() -> set[str]:
    """
    Return the base exports that optional files reference.

    These are the forward_to/input targets an optional file names that are
    NOT declared in an optional file itself.

    A "type.label" is referenced when an optional file forwards into
    "<type>.<label>.receiver" (or .input), or consumes
    "<type>.<label>.targets" or "<type>.<label>.output" -- the manifest
    14.4 extension points include two .targets exports, and .output is
    how one relabel feeds another, so the scan must see all four. Leaving
    .output out meant an overlay could consume the output of a base
    relabel -- an internal stage of a domain pipeline, not a published
    export -- and no gate would notice.
    References that resolve to an optional-internal component (the
    file's own graph) are subtracted; what remains MUST exist in base.
    Deliberately NOT intersected with base: the anti-drift gate asserts
    referenced <= base, so a typo'd base reference (absent from base AND
    optional) fails the fast static gate instead of being silently
    filtered away.
    """
    referenced: set[str] = set()
    for text in optional_sources().values():
        for typ, label in re.findall(
            r"([a-z][\w.]+)\.([\w]+)\.(?:receiver|input|targets|output)", text
        ):
            referenced.add(f"{typ}.{label}")
    return referenced - optional_component_names()


def extension_point_exports() -> set[str]:
    """
    Full export names ("<type>.<label>.<export>") overlays take from base.

    The manifest 14.4 table lists exports, not components, so binding an
    overlay to it needs the export kind as well: base may declare a
    component whose receiver is public and whose output is not.
    """
    internal = optional_component_names()
    exports: set[str] = set()
    for text in optional_sources().values():
        for typ, label, kind in re.findall(
            r"([a-z][\w.]+)\.([\w]+)\.(receiver|input|targets|output)", text
        ):
            if f"{typ}.{label}" not in internal:
                exports.add(f"{typ}.{label}.{kind}")
    return exports


def _blocks(text: str, header: str) -> list[tuple[str, str]]:
    """
    Return (label, body) for every ``<header> "<label>" {`` block.

    Indentation-aware, unlike the line-anchored regexes elsewhere in this
    module: the database domain declares its scrapes inside a ``foreach``,
    so anchoring at column zero would silently skip the four blocks a
    whole-config gate most needs to see.
    """
    opening = re.compile(
        rf'(?m)^(?P<indent>\t*){re.escape(header)} "(?P<label>\w+)" \{{$'
    )
    found: list[tuple[str, str]] = []
    for block in opening.finditer(text):
        closing = re.search(
            rf"(?m)^{block['indent']}\}}$", text[block.end() :]
        )
        if closing is None:
            raise AssertionError(
                f'unterminated {header} "{block["label"]}" block'
            )
        found.append(
            (block["label"], text[block.end() : block.end() + closing.start()])
        )
    return found


def scrape_blocks() -> list[tuple[str, str, str]]:
    """
    Return (file, label, body) for every prometheus.scrape in the reference.

    Base and overlays together: a scrape is a scrape wherever it lives,
    and the hardening gates must not stop at the directory boundary. The
    label is not unique on its own -- the database domain declares four
    blocks named "db" -- so the file name travels with it.
    """
    found = [
        (name, label, body)
        for name, text in {**sources(), **optional_sources()}.items()
        for label, body in _blocks(text, "prometheus.scrape")
    ]
    if not found:
        raise AssertionError("no prometheus.scrape blocks found")
    return found


def _all_text() -> str:
    """Return base plus optional config text (env scan spans overlays too)."""
    return "\n".join([*sources().values(), *optional_sources().values()])


def config_text() -> str:
    """Public alias of the combined base+optional config text."""
    return _all_text()


def env_defaults() -> dict[str, set[str]]:
    """
    Env var -> set of its literal coalesce defaults found.

    Scans base and optional files (an optional overlay may parameterise its
    own values).
    """
    found: dict[str, set[str]] = {}
    pattern = (
        r'coalesce\(sys\.env\("(RU_3OPS_DISCOVERY_[A-Z0-9_]+)"\),'
        r'\s*"([^"]*)"\)'
    )
    for name, default in re.findall(pattern, _all_text()):
        found.setdefault(name, set()).add(default)
    return found


def env_calls_without_default() -> set[str]:
    """
    sys.env calls that are not wrapped in coalesce(..., literal).

    Scans base and optional files (an optional overlay may parameterise its
    own values).
    """
    every = set(
        re.findall(
            r'sys\.env\("(RU_3OPS_DISCOVERY_[A-Z0-9_]+)"\)', _all_text()
        )
    )
    return every - set(env_defaults())


def _rules(text: str) -> list[str]:
    """Split a file into rule { ... } bodies (flat, no nesting)."""
    return re.findall(r"(?ms)^\s*rule \{\n(.*?)^\s*\}$", text)


def _keep_regex(rule: str, label_suffix: str) -> str | None:
    """Return the regex of a keep-rule keyed on the contract label."""
    if f"{_LABEL}_{label_suffix}" not in rule:
        return None
    if not re.search(r'action\s*=\s*"keep"', rule):
        return None
    m = re.search(r'regex\s*=\s*"(.*)"', rule)
    return m.group(1) if m else None


def _profile_keep(regex: str, scrape: str) -> tuple[str, bool]:
    """
    Split a profile keep-regex into (profile name, serves the default).

    Parsed rather than stripped. ``regex.strip("()?")`` returned the same
    name for ``(fast-v1)`` and ``(fast-v1)?`` -- and that trailing ``?``
    is the entire difference between a filter that serves marked targets
    and one that also swallows every unmarked one. A profile pair copied
    with the marker left on would have scraped every default target a
    second time and satisfied every gate while doing it.
    """
    match = re.fullmatch(r"\(([\w-]+)\)(\?)?", regex)
    if match is None:
        raise AssertionError(
            f"scrape {scrape}: profile keep-regex {regex!r} is not a single "
            f"alternative; one filter must serve exactly one profile"
        )
    return match.group(1), match.group(2) is not None


def _profile_pairs(
    text: str, label_suffix: str, domain: str
) -> tuple[dict[str, dict[str, str]], frozenset[str]]:
    """
    Pair every prometheus.scrape with the profile filter it references.

    Returns the (profile -> params) map and the set of profiles whose
    filter also accepts an unset label, i.e. the ones serving as the
    domain default.

    Reference-based on purpose: the scrape's ``targets`` expression names
    the filter relabel whose keep-rule defines the profile, so a fast
    filter wired into a slow scrape fails here -- positional pairing
    would only compare counts. Component labels must derive from the
    full profile name (``fast-v1`` -> ``<domain>_fast_v1``) so profile
    successors (8.1) never collide with taken names.
    """
    relabels = dict(
        re.findall(r'(?ms)^discovery\.relabel "(\w+)" \{\n(.*?)^\}$', text)
    )
    pairs: dict[str, dict[str, str]] = {}
    defaults: set[str] = set()
    for scrape_name, body in re.findall(
        r'(?ms)^prometheus\.scrape "(\w+)" \{\n(.*?)^\}$', text
    ):
        ref = re.search(
            r"targets\s*=\s*discovery\.relabel\.(\w+)\.output", body
        )
        interval = re.search(r'scrape_interval\s*=\s*"(\S+?)"', body)
        timeout = re.search(r'scrape_timeout\s*=\s*"(\S+?)"', body)
        if ref is None or interval is None or timeout is None:
            raise AssertionError(
                f"scrape {scrape_name}: no relabel reference or interval"
            )
        profile = None
        serves_default = False
        for rule in _rules(relabels.get(ref.group(1), "")):
            regex = _keep_regex(rule, label_suffix)
            if regex is not None:
                profile, serves_default = _profile_keep(regex, scrape_name)
        if profile is None:
            raise AssertionError(
                f"scrape {scrape_name}: referenced relabel {ref.group(1)} "
                f"has no {label_suffix} keep-rule"
            )
        expected = f"{domain}_{profile.replace('-', '_')}"
        if scrape_name != expected or ref.group(1) != expected:
            raise AssertionError(
                f"profile {profile}: components {ref.group(1)}/"
                f"{scrape_name} do not follow the {expected} naming"
            )
        pairs[profile] = {
            "interval": interval.group(1),
            "timeout": timeout.group(1),
        }
        if serves_default:
            defaults.add(profile)
    return pairs, frozenset(defaults)


def scrape_pairs() -> dict[str, dict[str, str]]:
    """Return implemented scrape profiles: name -> {interval, timeout}."""
    return _profile_pairs(
        sources()["020_metrics.alloy"], "metrics_profile", "metrics"
    )[0]


def default_scrape_profiles() -> frozenset[str]:
    """Metrics profiles whose filter also accepts an unset profile label."""
    return _profile_pairs(
        sources()["020_metrics.alloy"], "metrics_profile", "metrics"
    )[1]


def default_blackbox_scrape_profiles() -> frozenset[str]:
    """Blackbox profiles whose filter also accepts an unset profile label."""
    return _profile_pairs(
        sources()["035_blackbox.alloy"], "blackbox_profile", "blackbox"
    )[1]


def metrics_type_allowlist() -> set[str]:
    """
    Values accepted by the metrics.type keep-rule in 020.

    The other domains bind their type/module allowlists to the manifest
    by a gate -- database.type, the blackbox modules, the snmp modules.
    This one was a bare literal in the config with nothing on the other
    end, which is how a domain grows a second accepted type in one place
    only.
    """
    for rule in _rules(sources()["020_metrics.alloy"]):
        regex = _keep_regex(rule, "metrics_type")
        if regex is not None:
            return set(regex.strip("()").split("|"))
    raise AssertionError("metrics.type keep-rule not found in 020")


def snmp_relabel_modules() -> set[str]:
    """
    Return modules accepted by the snmp module keep-rule in 037.

    The source label is the plain ``module`` key from the device YAML (a
    file-provider domain), not a docker-label prefix -- so this cannot reuse
    the blackbox helper.
    """
    text = optional_sources()["037_snmp.alloy"]
    for rule in _rules(text):
        if re.search(r'source_labels\s*=\s*\["module"\]', rule) and re.search(
            r'action\s*=\s*"keep"', rule
        ):
            m = re.search(r'regex\s*=\s*"\(([\w|]+)\)"', rule)
            if m:
                return set(m.group(1).split("|"))
    raise AssertionError("snmp module keep-rule not found in 037")


def snmp_scrape_pairs() -> dict[str, dict[str, str]]:
    """
    Return implemented snmp scrape profiles (name -> params).

    The domain is domain-wide: the profile name is set on the config side via
    a ``snmp_profile`` set-rule in ``discovery.relabel.snmp`` (there is no
    per-target keep-rule to carry it), and interval/timeout come from the
    single scrape block. Both lookups are order-independent within the rule
    body so ``alloy fmt`` reordering cannot break them.
    """
    text = optional_sources()["037_snmp.alloy"]
    name: str | None = None
    for rule in _rules(text):
        if re.search(r'target_label\s*=\s*"snmp_profile"', rule):
            m = re.search(r'replacement\s*=\s*"([\w-]+)"', rule)
            if m:
                name = m.group(1)
                break
    if name is None:
        raise AssertionError("snmp_profile set-rule not found in 037")
    interval = re.search(r'scrape_interval\s*=\s*"(\S+?)"', text)
    timeout = re.search(r'scrape_timeout\s*=\s*"(\S+?)"', text)
    if interval is None or timeout is None:
        raise AssertionError("snmp scrape block not found in 037")
    return {name: {"interval": interval.group(1), "timeout": timeout.group(1)}}


def logs_source_targets() -> str:
    """Return the targets expression of loki.source.docker in 040."""
    text = sources()["040_logs.alloy"]
    block = re.search(
        r'(?ms)^loki\.source\.docker "containers" \{\n(.*?)^\}$', text
    )
    if block is None:
        raise AssertionError("loki.source.docker block not found in 040")
    m = re.search(r"targets\s*=\s*(\S+)", block.group(1))
    if m is None:
        raise AssertionError("targets expression not found in 040 source")
    return m.group(1)


def port_presence_keep_regexes() -> dict[str, str]:
    """
    Domain -> regex of the presence keep-rule on the declared port label.

    discovery.docker emits a portless fallback target (no
    __meta_docker_port_private) for a container with no exposed TCP
    ports; keepequal alone then compares two empty strings and passes
    the target. The presence keep is what makes the mandatory port
    label fail-closed (manifest 10.1.1, 10.4.1, 11).
    """
    found: dict[str, str] = {}
    for domain, file, suffix in (
        ("metrics", "020_metrics.alloy", "metrics_port"),
        ("blackbox", "035_blackbox.alloy", "blackbox_port"),
    ):
        for rule in _rules(sources()[file]):
            regex = _keep_regex(rule, suffix)
            if regex is not None:
                found[domain] = regex
    return found


def job_presence_keep_regex() -> str | None:
    """Return the regex of the metrics.job presence keep-rule in 020."""
    for rule in _rules(sources()["020_metrics.alloy"]):
        regex = _keep_regex(rule, "metrics_job")
        if regex is not None:
            return regex
    return None


def snmp_name_default_rule() -> tuple[str, str]:
    """
    Return (regex, replacement) of the name-default rule in 037.

    prometheus.exporter.snmp rejects its WHOLE targets list when any row
    lacks ``name``, so the reference must default it (the manifest 10.6
    keeps ``name`` optional). The rule concatenates name;address and
    matches only when name is empty, so a declared name always wins.
    """
    text = optional_sources()["037_snmp.alloy"]
    for rule in _rules(text):
        if not re.search(r'target_label\s*=\s*"name"', rule):
            continue
        if not re.search(r'source_labels\s*=\s*\["name", "address"\]', rule):
            continue
        regex_m = re.search(r'regex\s*=\s*"(.*)"', rule)
        repl_m = re.search(r'replacement\s*=\s*"(.*)"', rule)
        if regex_m and repl_m:
            return regex_m.group(1), repl_m.group(1)
    raise AssertionError("snmp name-default rule not found in 037")


def log_profile_allowlist() -> set[str]:
    """Names accepted by the log_profile allowlist rule in 040."""
    text = sources()["040_logs.alloy"]
    for rule in _rules(text):
        if (
            f"{_LABEL}_logs_profile" in rule
            and 'target_label = "log_profile"' in rule
        ):
            m = re.search(r'regex\s*=\s*"\(([\w|-]+)\)"', rule)
            if m:
                return set(m.group(1).split("|"))
    raise AssertionError("log_profile allowlist rule not found in 040")


def dispatcher_profiles() -> set[str]:
    """Profiles addressed by stage.match selectors in 050."""
    text = sources()["050_log-profiles.alloy"]
    return set(re.findall(r'\{log_profile="([\w-]+)"\}', text))


def promoted_stream_labels() -> set[str]:
    """
    Stream labels produced by the docker logs path (040 and 050).

    Two promotion mechanisms are covered: relabel ``target_label`` and
    the static ``labels`` block in 040, plus any ``stage.labels`` block
    in the 050 profile dispatcher. Content parsed in 050 must land in
    structured metadata, never in stream labels (manifest 6.2); a
    ``stage.labels`` there would promote attacker-controlled content, so
    it is scanned even though the reference uses only
    ``stage.structured_metadata`` today.
    """
    text = sources()["040_logs.alloy"]
    labels = {
        name
        for name in re.findall(r'target_label\s*=\s*"(\w+)"', text)
        if not name.startswith("__")
    }
    static_block = re.search(r"(?ms)labels = \{\n(.*?)^\s*\}$", text)
    if static_block is None:
        raise AssertionError("static labels block not found in 040")
    labels.update(
        re.findall(r"^\s*(\w+)\s*=", static_block.group(1), re.MULTILINE)
    )
    dispatcher = sources()["050_log-profiles.alloy"]
    for block in re.findall(
        r"(?ms)stage\.labels \{\n(.*?)^\s*\}$", dispatcher
    ):
        values = re.search(r"(?ms)values = \{\n(.*?)^\s*\}", block)
        if values:
            labels.update(
                re.findall(r"^\s*(\w+)\s*=", values.group(1), re.MULTILINE)
            )
    return labels


def db_types_implemented() -> set[str]:
    """Database types with a discovery.relabel keep-rule in 030."""
    text = sources()["030_database.alloy"]
    types: set[str] = set()
    for rule in _rules(text):
        regex = _keep_regex(rule, "database_type")
        if regex is not None:
            types.update(regex.strip("()").split("|"))
    if not types:
        raise AssertionError("no database type keep-rules found in 030")
    return types


def db_enrich_blocks() -> dict[str, str]:
    """Bodies of the discovery.relabel enrich_* blocks nested in 030."""
    blocks = dict(
        re.findall(
            r'(?ms)discovery\.relabel "enrich_(\w+)" \{\n(.*?)^\t\t\}$',
            sources()["030_database.alloy"],
        )
    )
    if not blocks:
        raise AssertionError("no enrich blocks found in 030")
    return blocks


def files_with_host_provenance() -> set[str]:
    """File names (base and optional) attaching host = constants.hostname."""
    return {
        name
        for name, text in {**sources(), **optional_sources()}.items()
        if "constants.hostname" in text
    }


def files_with_collector_provenance() -> set[str]:
    """File names (base and optional) attaching the collector label."""
    return {
        name
        for name, text in {**sources(), **optional_sources()}.items()
        if re.search(
            r'collector\s*=\s*"alloy"|target_label\s*=\s*"collector"', text
        )
    }


def secret_id_regexes() -> list[str]:
    """Every secret-id keep regex in 030 (all pipelines)."""
    text = sources()["030_database.alloy"]
    found = [
        regex
        for rule in _rules(text)
        if (regex := _keep_regex(rule, "database_secret_id")) is not None
    ]
    if not found:
        raise AssertionError("no secret-id keep-rules found in 030")
    return found


def db_default_ports() -> dict[str, str]:
    """Database type -> literal default port replacement in 030."""
    text = sources()["030_database.alloy"]
    # Phase 1: one pipeline (postgres). The relabel component name
    # carries the type: discovery.relabel "database_<type>".
    ports: dict[str, str] = {}
    for name, body in re.findall(
        r'(?ms)discovery\.relabel "database_(\w+)" \{\n(.*?)^\}$', text
    ):
        m = re.search(
            r'(?ms)target_label = "__tmp_database_port"\n\s*'
            r'replacement\s*=\s*"(\d+)"',
            body,
        )
        if m:
            ports[name] = m.group(1)
    if not ports:
        raise AssertionError("no default database ports found in 030")
    return ports


def db_profile_allowlists() -> dict[str, set[str]]:
    """
    Database type -> profile allowlist of its keep-rule in 030.

    The empty alternative (unset label -> default profile) is part of the
    regex and is returned as "" so the gate can assert it explicitly.
    """
    allowlists: dict[str, set[str]] = {}
    for name, body in re.findall(
        r'(?ms)discovery\.relabel "database_(\w+)" \{\n(.*?)^\}$',
        sources()["030_database.alloy"],
    ):
        for rule in _rules(body):
            regex = _keep_regex(rule, "database_profile")
            if regex is not None:
                allowlists[name] = set(regex.strip("()").split("|"))
    if not allowlists:
        raise AssertionError("no database profile keep-rules found in 030")
    return allowlists


def db_profile_map_keys() -> list[set[str]]:
    """
    Key sets of exporter argument maps indexed by the profile label.

    The postgres and mysql templates pick collector lists via
    ``{ ... }[coalesce(each[<profile label>], ...)]``; indexing a missing
    key is a load-time error, so every map must cover the full manifest
    8.4 allowlist (the relabel keep-rule guards only non-empty garbage).
    """
    maps = re.findall(
        r"(?ms)= \{\n(.*?)^\s*\}\[coalesce\(each\["
        rf'"{_LABEL}_database_profile"\]',
        sources()["030_database.alloy"],
    )
    if not maps:
        raise AssertionError("no profile-indexed argument maps found in 030")
    return [set(re.findall(r'"([\w-]+)"\s*=', body)) for body in maps]


def otel_promoted_stream_labels() -> set[str]:
    """
    Labels 060_otel promotes to Loki streams via the resource-hint.

    The loki.resource.labels / loki.attribute.labels hint values name OTLP
    attributes; Alloy sanitizes them to Prometheus label form (dots and
    dashes -> underscores). Empty if there is no optional otel file.
    """
    labels: set[str] = set()
    text = optional_sources().get("060_otel.alloy", "")
    for hint in re.findall(
        r'key\s*=\s*"loki\.(?:resource|attribute)\.labels".*?'
        r'value\s*=\s*"([^"]*)"',
        text,
        re.DOTALL,
    ):
        for attr in hint.split(","):
            name = attr.strip()
            if name:
                labels.add(re.sub(r"[.-]", "_", name))
    return labels


def host_log_stream_labels() -> set[str]:
    """
    Return the static stream labels 080_host-logs attaches to journal streams.

    loki.source.journal promotes only its static ``labels`` map to stream
    labels; the manifest 6.2 allowlist gate unions these so no write path
    into loki.write bypasses the cardinality discipline. Empty if there is
    no optional host-logs file.
    """
    text = optional_sources().get("080_host-logs.alloy", "")
    block = re.search(r"(?ms)labels\s*=\s*\{\n(.*?)^\s*\}", text)
    if block is None:
        return set()
    return set(re.findall(r"^\s*(\w+)\s*=", block.group(1), re.MULTILINE))


def blackbox_config_modules() -> set[str]:
    """
    Return modules defined in the blackbox exporter `config` YAML.

    A module entry is identified by its leading `prober` key: nested
    prober-option maps (tcp:, tls_config:) open a brace too but never
    start with `prober`, so they must not count as modules.
    """
    text = sources()["035_blackbox.alloy"]
    m = re.search(r"modules:\s*\{(.*)\}", text)
    if m is None:
        raise AssertionError("blackbox exporter config modules not found")
    return set(re.findall(r"(\w+):\s*\{\s*prober", m.group(1)))


def blackbox_relabel_modules() -> set[str]:
    """Return modules accepted by the blackbox module keep-rule in 035."""
    text = sources()["035_blackbox.alloy"]
    for rule in _rules(text):
        if f"{_LABEL}_blackbox_module" in rule and re.search(
            r'action\s*=\s*"keep"', rule
        ):
            m = re.search(r'regex\s*=\s*"\(([\w|]+)\)"', rule)
            if m:
                return set(m.group(1).split("|"))
    raise AssertionError("blackbox module keep-rule not found in 035")


def blackbox_scrape_pairs() -> dict[str, dict[str, str]]:
    """Return implemented blackbox scrape profiles (name -> params)."""
    return _profile_pairs(
        sources()["035_blackbox.alloy"], "blackbox_profile", "blackbox"
    )[0]


def blackbox_composition_modules() -> set[str]:
    """
    Modules with a target-composition rule in the shared blackbox relabel.

    Composition is fail-open: a module missing here would keep the raw
    discovery address as the probe target instead of being dropped, so
    the gate pairing this set with the keep-rule allowlist and the
    exporter config is mandatory, not cosmetic.
    """
    text = sources()["035_blackbox.alloy"]
    found = set()
    for rule in _rules(text):
        if f"{_LABEL}_blackbox_module" not in rule:
            continue
        if not re.search(r'target_label\s*=\s*"__address__"', rule):
            continue
        m = re.search(r'regex\s*=\s*"(\w+)\\\\\|', rule)
        if m:
            found.add(m.group(1))
    if not found:
        raise AssertionError("no composition rules found in 035")
    return found


def _cadvisor_text() -> str:
    return optional_sources()["075_container-metrics.alloy"]


def _cadvisor_relabel_block() -> str:
    # The series-side assertions are about rules INSIDE
    # prometheus.relabel (cut its body first, like db_default_ports),
    # not about component order in the file.
    block = re.search(
        r'(?ms)^prometheus\.relabel "cadvisor" \{\n(.*?)^\}',
        _cadvisor_text(),
    )
    if block is None:
        raise AssertionError("prometheus.relabel block not found in 075")
    return block.group(1)


def cadvisor_allowlisted_labels() -> set[str]:
    """Docker label keys 075 allowlists onto cadvisor series."""
    block = re.search(
        r"(?ms)allowlisted_container_labels\s*=\s*\[\n(.*?)^\s*\]",
        _cadvisor_text(),
    )
    if block is None:
        raise AssertionError(
            "allowlisted_container_labels block not found in 075"
        )
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def cadvisor_store_container_labels() -> str:
    """Literal store_container_labels value in 075."""
    m = re.search(r"store_container_labels\s*=\s*(\w+)", _cadvisor_text())
    if m is None:
        raise AssertionError("store_container_labels not found in 075")
    return m.group(1)


def cadvisor_disable_root_cgroup_stats() -> str:
    """Literal disable_root_cgroup_stats value in 075."""
    m = re.search(r"disable_root_cgroup_stats\s*=\s*(\w+)", _cadvisor_text())
    if m is None:
        raise AssertionError("disable_root_cgroup_stats not found in 075")
    return m.group(1)


def cadvisor_docker_only() -> str:
    """Literal docker_only value in 075."""
    m = re.search(r"docker_only\s*=\s*(\w+)", _cadvisor_text())
    if m is None:
        raise AssertionError("docker_only not found in 075")
    return m.group(1)


def cadvisor_relabel_target_labels() -> set[str]:
    """Every non-internal target_label 075 sets (both relabel stages)."""
    labels = {
        name
        for name in re.findall(r'target_label\s*=\s*"(\w+)"', _cadvisor_text())
        if not name.startswith("__")
    }
    if not labels:
        raise AssertionError("no relabel target_labels found in 075")
    return labels


def cadvisor_copy_rule_sources() -> set[str]:
    """source_labels of the copy rules in 075's prometheus.relabel."""
    sources = set()
    for rule in _rules(_cadvisor_relabel_block()):
        m = re.search(r'source_labels\s*=\s*\["([^"]+)"\]', rule)
        if m:
            sources.add(m.group(1))
    if not sources:
        raise AssertionError("no copy rules found in 075")
    return sources


def cadvisor_relabel_rule_kinds() -> list[str]:
    """Ordered rule kinds in 075's prometheus.relabel block."""
    kinds = []
    for rule in _rules(_cadvisor_relabel_block()):
        if re.search(r'action\s*=\s*"labeldrop"', rule):
            kinds.append("labeldrop")
        elif "source_labels" in rule:
            kinds.append("copy")
        else:
            kinds.append("target")
    if not kinds:
        raise AssertionError("no relabel rules found in 075")
    return kinds


def cadvisor_labeldrop_regex() -> str:
    """Mandatory raw-label labeldrop regex in 075."""
    for rule in _rules(_cadvisor_relabel_block()):
        if re.search(r'action\s*=\s*"labeldrop"', rule):
            m = re.search(r'regex\s*=\s*"(.*)"', rule)
            if m:
                return m.group(1)
    raise AssertionError("labeldrop rule not found in 075")
