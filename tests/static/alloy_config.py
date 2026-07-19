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

_LABEL = "__meta_docker_container_label_ru_3ops_discovery"


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


def _all_text() -> str:
    return "\n".join(sources().values())


def env_defaults() -> dict[str, set[str]]:
    """Env var -> set of its literal coalesce defaults found."""
    found: dict[str, set[str]] = {}
    pattern = (
        r'coalesce\(sys\.env\("(RU_3OPS_DISCOVERY_[A-Z0-9_]+)"\),'
        r'\s*"([^"]*)"\)'
    )
    for name, default in re.findall(pattern, _all_text()):
        found.setdefault(name, set()).add(default)
    return found


def env_calls_without_default() -> set[str]:
    """sys.env calls that are not wrapped in coalesce(..., literal)."""
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


def scrape_pairs() -> dict[str, dict[str, str]]:
    """Return implemented scrape profiles: name -> {interval, timeout}."""
    text = sources()["020_metrics.alloy"]
    profiles = []
    for rule in _rules(text):
        regex = _keep_regex(rule, "metrics_profile")
        if regex is not None:
            # "(normal-v1)?" -> normal-v1 (the ? makes it the default).
            profiles.append(regex.strip("()?"))
    intervals = re.findall(r'scrape_interval\s*=\s*"(\S+?)"', text)
    timeouts = re.findall(r'scrape_timeout\s*=\s*"(\S+?)"', text)
    if not (len(profiles) == len(intervals) == len(timeouts)):
        raise AssertionError(
            "profile keep-rules and scrape blocks in 020 do not pair up"
        )
    return {
        name: {"interval": interval, "timeout": timeout}
        for name, interval, timeout in zip(
            profiles, intervals, timeouts, strict=True
        )
    }


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
