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
    # The forbidden profile in 8.1 (and any other in-prose example, like
    # the 10.1.2 labels illustration) is addressed by no anchor:
    # extraction functions above touch only their own sections, so
    # nothing to assert beyond exactness already pinned; this test
    # documents the property.
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


def test_an_anchor_addresses_its_own_section_not_the_subtree() -> None:
    # section() keeps subsections, because a gate reading prose wants the
    # whole domain; table() and code_block() must not, because they
    # address by POSITION. Section 10.1 has no table of its own -- the
    # labels table belongs to 10.1.1 -- so a subtree-wide anchor would
    # hand back the subsection's table under the parent's number.
    assert "10.1.1" in md.section("10.1")
    assert "10.1.1" not in md.section("10.1", subsections=False)
    with pytest.raises(md.AnchorError):
        md.table("10.1")


def test_a_numbered_document_title_fails_as_a_missing_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The stop-regex is built as "#{2,level}"; at level 1 that is invalid
    # rather than merely unmatched, so it raised re.error instead of the
    # error type every caller handles. The real manifest has no numbered
    # level-1 heading, which is why this needs a substitute document
    # rather than an anchor into the real one.
    monkeypatch.setattr(md, "_text", lambda: "# 1. Title\n\nbody\n")
    with pytest.raises(md.AnchorError, match="document title"):
        md.section("1")
