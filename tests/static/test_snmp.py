"""Manifest 8.5/10.6 vs alloy-optional/037_snmp.alloy."""

from pathlib import Path

import pytest
import yaml

from tests.static import alloy_config as ac
from tests.static import asymmetries
from tests.static import manifest_doc as md
from tools import snmp_fixtures, stack_secrets


def test_implemented_pairs_match_manifest_parameters() -> None:
    manifest = md.snmp_scrape_profiles()
    for name, params in ac.snmp_scrape_pairs().items():
        assert name in manifest, f"{name} is not a manifest 8.5 profile"
        assert params == manifest[name], (
            f"{name}: config {params} != manifest {manifest[name]}"
        )


def test_scrape_profile_asymmetry_is_exact() -> None:
    manifest = set(md.snmp_scrape_profiles())
    implemented = set(ac.snmp_scrape_pairs())
    allowed = set(asymmetries.SNMP_SCRAPE_PROFILES_UNIMPLEMENTED)
    assert implemented | allowed == manifest
    assert implemented & allowed == set()


def test_every_target_gets_a_name() -> None:
    # prometheus.exporter.snmp refuses the WHOLE targets list when any
    # row lacks `name` (the check runs on every re-evaluation of the
    # arguments), so one nameless device row would take down the entire
    # domain -- a failure mode manifest 11 does not allow. The manifest
    # 10.6 keeps `name` optional, so the reference defaults it to the
    # device address; the rule must fire only when name is empty.
    assert ac.snmp_name_default_rule() == (";(.+)", "$1")


def test_module_allowlist_is_exact_and_disjoint_from_gaps() -> None:
    # One-sided: the snmp modules live in the exporter's built-in snmp.yml, so
    # there is no in-repo config set to cross-check (unlike blackbox). Assert
    # the shipped allowlist against the hand-maintained literal, and guard that
    # no shipped module is on the documented-gap list.
    shipped = ac.snmp_relabel_modules()
    assert shipped == {"if_mib", "system"}
    unshipped = set(asymmetries.SNMP_MODULES_UNIMPLEMENTED)
    assert shipped & unshipped == set()


def test_device_name_becomes_a_series_label() -> None:
    # The exporter consumes `name` into __param_name, which is dropped
    # on scrape, so without a copy to a non-reserved label the device
    # name never reaches the series (instance carries the address).
    text = ac.optional_sources()["037_snmp.alloy"]
    assert 'source_labels = ["name"]\n\t\ttarget_label  = "device"' in text, (
        "no name -> device copy rule in 037"
    )


def test_module_gap_entries_appear_in_manifest() -> None:
    # The disjointness check above can never retire a gap entry for a
    # module the manifest no longer mentions -- a phantom name satisfies
    # it forever. Require every entry to exist in the 10.6 text.
    for module in asymmetries.SNMP_MODULES_UNIMPLEMENTED:
        assert f"`{module}`" in md.section("10.6"), (
            f"{module}: dead SNMP_MODULES_UNIMPLEMENTED entry, "
            "manifest 10.6 no longer mentions it"
        )


def test_auth_version_allowlist_matches_the_validator() -> None:
    # 10.6.1 names the validator as the repository's single control point
    # for the auth file, so the two must not drift apart. The exporter
    # itself accepts 1..3; SNMPv1 stays out by contract.
    assert md.snmp_auth_versions() == set(snmp_fixtures.SNMP_VERSIONS)
    assert 1 not in snmp_fixtures.SNMP_VERSIONS


def test_auth_level_fields_match_the_validator() -> None:
    manifest = md.snmp_auth_level_fields()
    validator = {
        level: set(fields)
        for level, fields in snmp_fixtures.REQUIRED_FIELDS_BY_LEVEL.items()
    }
    assert manifest == validator


def test_validator_rejects_a_non_mapping_profile() -> None:
    with pytest.raises(TypeError, match="snmp auth 'bad'"):
        snmp_fixtures.validate_auths({"bad": "community: public"})


def test_auth_enums_match_the_validator() -> None:
    manifest = md.snmp_auth_enums()
    assert manifest["security_level"] == set(snmp_fixtures.SECURITY_LEVELS)
    assert manifest["auth_protocol"] == set(snmp_fixtures.AUTH_PROTOCOLS)
    assert manifest["priv_protocol"] == set(snmp_fixtures.PRIV_PROTOCOLS)


@pytest.mark.parametrize(
    "profile",
    [
        pytest.param({"version": 1, "community": "public"}, id="snmpv1"),
        pytest.param({"version": 2}, id="v2c-without-community"),
        pytest.param({"version": 3, "username": "u"}, id="v3-without-level"),
        pytest.param(
            {
                "version": 3,
                "username": "u",
                "security_level": "authPriv",
                "password": "p",
                "auth_protocol": "SHA",
                "priv_protocol": "AES",
            },
            id="authPriv-without-priv-password",
        ),
        pytest.param(
            {
                "version": 3,
                "username": "u",
                "security_level": "authNoPriv",
                "password": "p",
                "auth_protocol": "ROT13",
            },
            id="unknown-auth-protocol",
        ),
    ],
)
def test_validator_rejects_invalid_profiles(
    profile: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="snmp auth 'bad'"):
        snmp_fixtures.validate_auths({"bad": profile})


def test_validator_accepts_the_shipped_fixture(tmp_path: Path) -> None:
    # The e2e/demo profile must satisfy its own contract: write_secrets is
    # the only producer of a real auth file, so a drift there would ship a
    # profile the manifest forbids.
    stack_secrets.write_secrets(tmp_path)
    written = (tmp_path / "snmp_auths.yaml").read_text(encoding="utf-8")
    auths = yaml.safe_load(written)["auths"]
    snmp_fixtures.validate_auths(auths)
    assert auths["netmon-v3"]["version"] in snmp_fixtures.SNMP_VERSIONS
