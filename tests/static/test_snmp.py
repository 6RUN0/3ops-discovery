"""Manifest 8.5/10.6 vs alloy-optional/037_snmp.alloy."""

from tests.static import alloy_config as ac
from tests.static import asymmetries
from tests.static import manifest_doc as md


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
