"""Manifest 8.2/10.4 vs 035_blackbox.alloy."""

from tests.static import alloy_config as ac
from tests.static import asymmetries
from tests.static import manifest_doc as md


def test_implemented_pairs_match_manifest_parameters() -> None:
    manifest = md.scrape_profiles()
    for name, params in ac.blackbox_scrape_pairs().items():
        assert name in manifest, f"{name} is not a manifest 8.2 profile"
        assert params == manifest[name], (
            f"{name}: config {params} != manifest {manifest[name]}"
        )


def test_scrape_profile_asymmetry_is_exact() -> None:
    manifest = set(md.scrape_profiles())
    implemented = set(ac.blackbox_scrape_pairs())
    allowed = set(asymmetries.BLACKBOX_SCRAPE_PROFILES_UNIMPLEMENTED)
    assert implemented | allowed == manifest
    assert implemented & allowed == set()


def test_module_allowlist_matches_exporter_config() -> None:
    # Config-internal consistency: the relabel keep-rule and the exporter
    # config must accept the same modules (manifest 10.4 lists modules as
    # open-ended examples, so there is no closed set to anchor against).
    # Plus a disjointness guard: no shipped module is on the documented-gap
    # list, so the two never silently drift into overlap.
    assert ac.blackbox_relabel_modules() == ac.blackbox_config_modules()
    unshipped = set(asymmetries.BLACKBOX_MODULES_UNIMPLEMENTED)
    assert ac.blackbox_config_modules() & unshipped == set()
