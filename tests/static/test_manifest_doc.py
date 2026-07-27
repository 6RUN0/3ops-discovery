"""Unit tests for the anchor-based manifest parser."""

import pytest

from tests.static import manifest_doc as md


def test_missing_section_raises_anchor_error() -> None:
    with pytest.raises(md.AnchorError, match="99"):
        md.section("99")


def test_scrape_profiles_anchor() -> None:
    profiles = md.scrape_profiles()
    assert profiles["normal-v1"] == {"interval": "30s", "timeout": "10s"}
    assert set(profiles) == {"fast-v1", "normal-v1", "slow-v1"}


def test_log_profiles_anchor() -> None:
    names = md.log_profiles()
    assert "raw-v1" in names
    assert "generic-json-v1" in names
    assert len(names) == 8


def test_db_types_anchor() -> None:
    assert md.db_types() == {
        "postgres",
        "mysql",
        "mariadb",
        "redis",
        "mongodb",
    }


def test_db_profiles_anchor() -> None:
    assert md.db_profiles() == {"basic-v1", "standard-v1", "extended-v1"}


def test_secret_id_pattern_anchor() -> None:
    assert md.secret_id_pattern() == "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"


def test_loki_allowlist_anchor() -> None:
    allow = md.loki_label_allowlist()
    assert {"service_name", "log_profile", "collector"} <= allow
    assert "trace_id" not in allow


def test_env_defaults_anchor() -> None:
    env = md.env_defaults()
    assert env["RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL"] == "30s"
    assert env["RU_3OPS_DISCOVERY_SECRETS_DIR"] == "/run/alloy-secrets"
    assert len(env) == 9  # 8 (base + host) + 1 snmp targets-file env (037)


def test_base_files_anchor() -> None:
    files = md.base_files()
    assert "010_discovery.alloy" in files
    assert len(files) == 7


def test_alloy_image_tag_anchor() -> None:
    assert md.alloy_image_tag() == "v1.17.1"


def test_counterexamples_not_extracted() -> None:
    # The fast-v1 illustration in 10.1.2 and the forbidden profile in
    # 8.1 are addressed by no anchor: extraction functions above touch
    # only their own sections, so nothing to assert beyond exactness
    # already pinned; this test documents the property.
    assert "fast-v1" in md.scrape_profiles()  # normative, from 8.2


def test_snmp_scrape_profiles_anchor() -> None:
    profiles = md.snmp_scrape_profiles()
    assert profiles == {
        "snmp-standard-v1": {"interval": "60s", "timeout": "30s"}
    }


def test_provenance_labels_anchor() -> None:
    labels = md.provenance_labels()
    assert {"container", "collector", "instance"} <= labels
    assert len(labels) == 8
