"""Manifest 8.2 vs 020_metrics.alloy."""

from tests.static import alloy_config as ac
from tests.static import asymmetries
from tests.static import manifest_doc as md


def test_implemented_pairs_match_manifest_parameters() -> None:
    manifest = md.scrape_profiles()
    for name, params in ac.scrape_pairs().items():
        assert name in manifest, f"{name} is not a manifest 8.2 profile"
        assert params == manifest[name], (
            f"{name}: config {params} != manifest {manifest[name]}"
        )


def test_asymmetry_table_is_exact() -> None:
    manifest = set(md.scrape_profiles())
    implemented = set(ac.scrape_pairs())
    allowed = set(asymmetries.SCRAPE_PROFILES_UNIMPLEMENTED)
    assert implemented | allowed == manifest
    assert implemented & allowed == set()


def test_port_keep_is_fail_closed() -> None:
    # Without a presence keep, a container that declares metrics.enabled
    # but no TCP ports rides the discovery.docker fallback target (no
    # __meta_docker_port_private) straight through keepequal ("" == "")
    # and gets scraped on port 80 (manifest 10.1.1 makes the label
    # mandatory, 11 makes its validation fail-closed).
    assert ac.port_presence_keep_regexes()["metrics"] == "(.+)"
