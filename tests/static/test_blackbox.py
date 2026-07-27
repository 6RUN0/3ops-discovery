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


def test_port_keep_is_fail_closed() -> None:
    # Same fallback-target hole as metrics, with a sharper edge: an icmp
    # probe composes a portless target, so without the presence keep a
    # container with no TCP ports gets probed while skipping the port
    # validation manifest 10.4.1 explicitly requires for ICMP too.
    assert ac.port_presence_keep_regexes()["blackbox"] == "(.+)"


def test_module_allowlist_matches_exporter_config() -> None:
    # Config-internal consistency: the relabel keep-rule, the exporter
    # config AND the target-composition rules must accept the same modules
    # (manifest 10.4 lists modules as open-ended examples, so there is no
    # closed set to anchor against). Composition is fail-open -- a module
    # accepted by the keep-rule but lacking a composition rule would probe
    # the raw discovery address -- so the three-way equality is mandatory.
    # Plus a disjointness guard: no shipped module is on the documented-gap
    # list, so the two never silently drift into overlap.
    assert ac.blackbox_relabel_modules() == ac.blackbox_config_modules()
    assert ac.blackbox_composition_modules() == ac.blackbox_config_modules()
    unshipped = set(asymmetries.BLACKBOX_MODULES_UNIMPLEMENTED)
    assert ac.blackbox_config_modules() & unshipped == set()


def test_module_gap_entries_appear_in_manifest() -> None:
    # A one-sided gap table can hold phantom names forever (the snmp
    # cisco_device entry died this way); require every entry to exist in
    # the manifest 10.4 text.
    for module in asymmetries.BLACKBOX_MODULES_UNIMPLEMENTED:
        assert f"`{module}`" in md.section("10.4"), (
            f"{module}: dead BLACKBOX_MODULES_UNIMPLEMENTED entry, "
            "manifest 10.4 no longer mentions it"
        )
