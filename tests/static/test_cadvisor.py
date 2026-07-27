"""Manifest 6.1 provenance vs alloy-optional/075_container-metrics.alloy."""

import re

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md

# One-way literal on purpose (pattern of test_snmp.py): no anchor
# extracts the contract label namespace from the manifest, and the
# com.docker.compose.* keys are not manifest content at all, so the
# gate pins the exact set here instead of deriving it.
CONTRACT_ALLOWLIST = {
    "ru.3ops.discovery.environment",
    "ru.3ops.discovery.team",
    "com.docker.compose.project",
    "com.docker.compose.service",
}


def _cadvisor_series_label(key: str) -> str:
    # The cadvisor sanitizeLabelName contract: [^a-zA-Z0-9_] -> "_",
    # then the container_label_ prefix (e2e pins the vendored fork).
    return "container_label_" + re.sub(r"[^a-zA-Z0-9_]", "_", key)


def test_relabel_targets_stay_within_contract_labels() -> None:
    assert ac.cadvisor_relabel_target_labels() <= md.provenance_labels()


def test_allowlist_is_exactly_the_contract_keys() -> None:
    assert ac.cadvisor_allowlisted_labels() == CONTRACT_ALLOWLIST


def test_store_container_labels_is_disabled() -> None:
    # allowlisted_container_labels only takes effect when this is false;
    # true would dump every docker label and env var into series labels.
    assert ac.cadvisor_store_container_labels() == "false"


def test_root_cgroup_stats_are_disabled() -> None:
    # After the mandatory id labeldrop the root-cgroup series would be
    # indistinguishable from an unlabeled container and would double
    # count the host, which 070_host-metrics already covers.
    assert ac.cadvisor_disable_root_cgroup_stats() == "true"


def test_docker_only_is_enabled() -> None:
    # The documented failure mode (near-empty output when the Docker
    # API is unreachable) holds only while this is true.
    assert ac.cadvisor_docker_only() == "true"


def test_docker_host_reuses_the_contract_env() -> None:
    assert (
        'coalesce(sys.env("RU_3OPS_DISCOVERY_DOCKER_HOST"), '
        '"unix:///var/run/docker.sock")'
    ) in ac.optional_sources()["075_container-metrics.alloy"]


def test_copy_rules_cover_every_allowlisted_label() -> None:
    # A typo in a source_labels name is a silent no-op (alloy validate
    # does not catch it), so pin allowlist -> copy-rule coverage.
    expected = {
        _cadvisor_series_label(key) for key in ac.cadvisor_allowlisted_labels()
    }
    assert expected <= ac.cadvisor_copy_rule_sources()


def test_labeldrop_is_the_last_relabel_rule() -> None:
    # The drop must run strictly after every copy rule.
    kinds = ac.cadvisor_relabel_rule_kinds()
    assert kinds.count("labeldrop") == 1
    assert kinds[-1] == "labeldrop"


def test_raw_container_labels_are_dropped() -> None:
    # The copy rules lift the contract names BEFORE the drop; raw
    # container_label_* plus id/name must never reach remote_write.
    assert ac.cadvisor_labeldrop_regex() == "container_label_.*|id|name"
