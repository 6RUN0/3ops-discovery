"""
vmagent implementation (implementations/vmagent/) vs the manifest.

The vmagent config is a second implementation of the metrics domain, so
it answers to the same tables as the reference: scrape profiles (8.2),
fail-closed mandatory labels (10.1.1, 11), provenance that a container
label cannot override (6.1, 13.5), no redirects (13.5), the 14.1
defaults and the section 14 registry row with its pinned image tag.
"""

import copy
from typing import Any

import noxfile as nx
import pytest

from tests.static import manifest_doc as md
from tests.static import vmagent_config as vc

#: Section 14.1 parameters that belong to the metrics domain and its output.
METRICS_ENV = {
    "RU_3OPS_DISCOVERY_DOCKER_HOST",
    "RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL",
    "RU_3OPS_DISCOVERY_REMOTE_WRITE_URL",
    "RU_3OPS_DISCOVERY_HOSTNAME",
}


def test_profiles_match_manifest() -> None:
    assert vc.profile_timings() == {
        name: (row["interval"], row["timeout"])
        for name, row in md.scrape_profiles().items()
    }


def test_unknown_profile_is_dropped() -> None:
    assert vc.profile_keep_regex() == (
        "(" + "|".join(sorted(md.scrape_profiles())) + ")?"
    )


def test_redirects_are_not_followed() -> None:
    assert all(
        c.get("follow_redirects") is False for c in vc.load()["scrape_configs"]
    )


def test_mandatory_labels_fail_closed() -> None:
    for label in ("metrics_port", "metrics_job"):
        assert vc.has_presence_keep(
            f"__meta_docker_container_label_ru_3ops_discovery_{label}"
        )
    assert vc.has_keep_if_equal("__meta_docker_port_private")


def test_provenance_is_set_after_user_labels() -> None:
    order = vc.target_label_order()
    for label in ("container", "collector", "host"):
        assert order.index(label) > max(
            order.index(u) for u in ("job", "instance", "environment", "team")
        )
    assert vc.static_value("collector") == "vmagent"


def test_entrypoint_defaults_match_manifest() -> None:
    table = md.env_defaults()
    defaults = vc.entrypoint_defaults()
    assert set(defaults) == METRICS_ENV
    for name, default in defaults.items():
        if name != "RU_3OPS_DISCOVERY_HOSTNAME":
            assert default == table[name]
    # The 14.1 cell is prose ("the collector's hostname"), not a value.
    assert defaults["RU_3OPS_DISCOVERY_HOSTNAME"] == "$(hostname)"


def test_every_placeholder_has_an_entrypoint_default() -> None:
    # vmagent keeps an unset %{NAME} as literal text and passes -dryRun, so
    # a variable the entrypoint does not default breaks discovery at
    # runtime unseen.
    assert vc.placeholders()
    assert vc.placeholders() <= set(vc.entrypoint_defaults())


def test_vmagent_pin_matches_registry() -> None:
    assert md.implementation_agent("vmagent").endswith(
        nx.VMAGENT_IMAGE.split(":")[1]
    )


def test_registry_lists_vmagent_for_metrics_only() -> None:
    assert md.implementations()["vmagent"] == {"metrics"}


def test_unknown_implementation_agent_is_an_anchor_error() -> None:
    with pytest.raises(md.AnchorError, match="no-such-agent"):
        md.implementation_agent("no-such-agent")


def test_vmagent_check_runs_through_the_entrypoint_both_ways() -> None:
    # One run proves the 14.1 defaults alone yield a loadable config, the
    # other the e2e values, tcp:// docker host and empty hostname included.
    assert nx.VMAGENT_CHECK_ENVS["defaults"] == {}
    assert set(nx.VMAGENT_CHECK_ENVS["e2e"]) == METRICS_ENV
    args = nx.vmagent_check_args({"A": "b"})
    assert args[args.index("-e") + 1] == "A=b"
    mount = args[args.index("-v") + 1]
    assert mount.split(":")[0].startswith("/")
    assert args[-3:] == [
        nx.VMAGENT_IMAGE,
        "/etc/vmagent/entrypoint.sh",
        "-dryRun",
    ]


def _rules() -> list[dict[str, Any]]:
    return copy.deepcopy(vc.relabel_rules())


def _default_profile() -> str:
    return md.default_profile("10.1.1", "ru.3ops.discovery.metrics.profile")


def test_only_the_default_profile_serves_unmarked_targets() -> None:
    assert vc.default_scrape_profiles() == {_default_profile()}


def test_default_profile_gate_catches_a_lost_optional_marker() -> None:
    # Without the "?" an unlabelled target passes the profile keep, gets
    # no interval rule and is scraped at vmagent's global 1m default.
    rules = _rules()
    for rule in rules:
        if rule.get("regex") == f"({_default_profile()})?":
            rule["regex"] = f"({_default_profile()})"
    assert vc.default_scrape_profiles(rules) == set()


def test_default_profile_gate_catches_half_a_default() -> None:
    rules = _rules()
    for rule in rules:
        if (
            rule.get("target_label") == "__scrape_timeout__"
            and rule.get("regex") == f"({_default_profile()})?"
        ):
            rule["regex"] = f"({_default_profile()})"
    with pytest.raises(vc.VmagentConfigError, match="disagree"):
        vc.default_scrape_profiles(rules)


def _keep_if_equal_index(rules: list[dict[str, Any]]) -> int:
    return next(
        i
        for i, rule in enumerate(rules)
        if rule.get("action") == "keep_if_equal"
    )


def test_port_match_gate_catches_a_wrong_comparand() -> None:
    rules = _rules()
    rules[_keep_if_equal_index(rules)]["source_labels"] = [
        "__meta_docker_port_private",
        "__meta_docker_port_public",
    ]
    assert not vc.has_keep_if_equal("__meta_docker_port_private", rules)


def test_port_match_gate_catches_a_missing_or_late_copy() -> None:
    rules = _rules()
    copy_rule = next(
        rule for rule in rules if rule.get("target_label") == vc.PORT_COPY
    )
    rules.remove(copy_rule)
    assert not vc.has_keep_if_equal("__meta_docker_port_private", rules)
    rules.insert(_keep_if_equal_index(rules) + 1, copy_rule)
    assert not vc.has_keep_if_equal("__meta_docker_port_private", rules)


def test_port_match_gate_catches_a_copy_of_another_label() -> None:
    rules = _rules()
    copy_rule = next(
        rule for rule in rules if rule.get("target_label") == vc.PORT_COPY
    )
    copy_rule["source_labels"] = [
        "__meta_docker_container_label_ru_3ops_discovery_metrics_job"
    ]
    assert not vc.has_keep_if_equal("__meta_docker_port_private", rules)
