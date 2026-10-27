"""
Structured reading of the vmagent implementation (implementations/vmagent/).

``scrape.yml`` is plain YAML, so it is parsed rather than scanned; the
helpers below extract the facts the static gates compare against the
manifest. ``entrypoint.sh`` is read by regex: it is POSIX sh, and the
only facts taken from it are the ``${NAME:-default}`` expansions that
apply the section 14.1 defaults.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
VMAGENT_DIR = REPO / "implementations" / "vmagent"
SCRAPE_CONFIG = VMAGENT_DIR / "scrape.yml"
ENTRYPOINT = VMAGENT_DIR / "entrypoint.sh"

PROFILE_LABEL = (
    "__meta_docker_container_label_ru_3ops_discovery_metrics_profile"
)

_DEFAULT_EXPANSION = re.compile(r"\$\{(RU_3OPS_DISCOVERY_\w+):-([^}]*)\}")
_PLACEHOLDER = re.compile(r"%\{(\w+)\}")
#: A timing regex that admits exactly one profile name; the trailing "?"
#: also admits the unset label, which only the default profile may do.
_ONE_PROFILE = re.compile(r"\(([a-z0-9-]+)\)(\?)?")
PORT_LABEL = "__meta_docker_container_label_ru_3ops_discovery_metrics_port"
PORT_COPY = "__tmp_metrics_port"

#: Relabel rules as parsed from YAML; ``None`` means the real scrape.yml.
Rules = list[dict[str, Any]] | None


class VmagentConfigError(AssertionError):
    """The vmagent config does not have the shape the gates expect."""


@cache
def load() -> dict[str, Any]:
    """Return the parsed ``scrape.yml``."""
    parsed = yaml.safe_load(SCRAPE_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise VmagentConfigError(f"{SCRAPE_CONFIG} is not a YAML mapping")
    return parsed


def relabel_rules() -> list[dict[str, Any]]:
    """Return the relabel rules of the single metrics scrape_config."""
    configs = load()["scrape_configs"]
    if len(configs) != 1:
        raise VmagentConfigError(
            f"expected one scrape_config for metrics, got {len(configs)}"
        )
    rules: list[dict[str, Any]] = configs[0]["relabel_configs"]
    return rules


def _action(rule: dict[str, Any]) -> str:
    action: str = rule.get("action", "replace")
    return action


def has_presence_keep(label: str) -> bool:
    """Return True if a keep rule drops targets whose ``label`` is empty."""
    return any(
        _action(rule) == "keep"
        and rule.get("source_labels") == [label]
        and rule.get("regex") in ("(.+)", ".+")
        for rule in relabel_rules()
    )


def has_keep_if_equal(label: str, rules: Rules = None) -> bool:
    """
    Return True if ``label`` is kept only when equal to the metrics.port copy.

    The copy must be made by an earlier rule, straight from the
    metrics.port label: a keep_if_equal against anything else (or against
    a copy made too late, hence empty) passes the wrong targets.
    """
    rules = relabel_rules() if rules is None else rules
    copied = False
    for rule in rules:
        if (
            _action(rule) == "replace"
            and rule.get("source_labels") == [PORT_LABEL]
            and rule.get("target_label") == PORT_COPY
            and rule.get("regex", "(.*)") == "(.*)"
            and rule.get("replacement", "$1") == "$1"
        ):
            copied = True
        if _action(rule) == "keep_if_equal" and rule.get("source_labels") == [
            label,
            PORT_COPY,
        ]:
            return copied
    return False


def target_label_order() -> list[str]:
    """Return every target_label in rule order."""
    return [
        rule["target_label"]
        for rule in relabel_rules()
        if "target_label" in rule
    ]


def static_value(label: str) -> str:
    """Return the constant a source-less rule writes into ``label``."""
    values = [
        rule["replacement"]
        for rule in relabel_rules()
        if rule.get("target_label") == label and "source_labels" not in rule
    ]
    if len(values) != 1:
        raise VmagentConfigError(f"{label}: {len(values)} static rules")
    value: str = values[0]
    return value


def profile_keep_regex() -> str:
    """Return the regex of the keep rule on the profile label."""
    regexes = [
        rule["regex"]
        for rule in relabel_rules()
        if _action(rule) == "keep"
        and rule.get("source_labels") == [PROFILE_LABEL]
    ]
    if len(regexes) != 1:
        raise VmagentConfigError(f"{len(regexes)} profile keep rules")
    regex: str = regexes[0]
    return regex


def _timing_rules(
    rules: Rules = None,
) -> list[tuple[str, bool, str, str]]:
    """Return (profile, admits unset, target label, value) per timing rule."""
    found = []
    for rule in relabel_rules() if rules is None else rules:
        target = rule.get("target_label")
        if target not in ("__scrape_interval__", "__scrape_timeout__"):
            continue
        if rule.get("source_labels") != [PROFILE_LABEL]:
            raise VmagentConfigError(f"{target} not driven by the profile")
        name = _ONE_PROFILE.fullmatch(rule["regex"])
        if name is None:
            raise VmagentConfigError(f"unexpected regex {rule['regex']!r}")
        found.append(
            (name.group(1), bool(name.group(2)), target, rule["replacement"])
        )
    return found


def profile_timings(rules: Rules = None) -> dict[str, tuple[str, str]]:
    """Return profile -> (__scrape_interval__, __scrape_timeout__)."""
    found: dict[str, dict[str, str]] = {}
    for name, _, target, value in _timing_rules(rules):
        found.setdefault(name, {})[target] = value
    return {
        name: (pair["__scrape_interval__"], pair["__scrape_timeout__"])
        for name, pair in found.items()
    }


def default_scrape_profiles(rules: Rules = None) -> set[str]:
    """
    Return the profiles whose timing rules also match an unset label.

    Both the interval and the timeout rule of a profile must agree: a
    target without the label that gets only one of them is scraped at
    vmagent's global default for the other.
    """
    admits: dict[str, set[bool]] = {}
    for name, optional, _, _ in _timing_rules(rules):
        admits.setdefault(name, set()).add(optional)
    mixed = sorted(name for name, kinds in admits.items() if len(kinds) > 1)
    if mixed:
        raise VmagentConfigError(f"timing rules disagree on unset: {mixed}")
    return {name for name, kinds in admits.items() if True in kinds}


def placeholders() -> set[str]:
    """Return every ``%{NAME}`` placeholder ``scrape.yml`` uses."""
    return set(_PLACEHOLDER.findall(SCRAPE_CONFIG.read_text(encoding="utf-8")))


def entrypoint_defaults() -> dict[str, str]:
    """Return env name -> default from ``entrypoint.sh`` expansions."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    defaults: dict[str, str] = {}
    for name, default in _DEFAULT_EXPANSION.findall(text):
        if defaults.setdefault(name, default) != default:
            raise VmagentConfigError(f"{name} has diverging defaults")
    if not defaults:
        raise VmagentConfigError(f"no ${{NAME:-default}} in {ENTRYPOINT}")
    return defaults
