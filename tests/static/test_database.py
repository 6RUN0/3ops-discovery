"""Manifest 10.2/8.4 vs 030_database.alloy."""

from tests.static import alloy_config as ac
from tests.static import asymmetries
from tests.static import manifest_doc as md


def test_db_types_asymmetry_is_exact() -> None:
    manifest = md.db_types()
    implemented = ac.db_types_implemented()
    allowed = set(asymmetries.DB_TYPES_UNIMPLEMENTED)
    assert implemented | allowed == manifest
    assert implemented & allowed == set()


def test_db_profile_allowlists_match_manifest() -> None:
    # Every pipeline must validate the profile label fail-closed against
    # the manifest 8.4 allowlist; "" is the unset-label default path.
    allowlists = ac.db_profile_allowlists()
    assert set(allowlists) == set(ac.db_default_ports())
    for allowlist in allowlists.values():
        assert allowlist == md.db_profiles() | {""}
    assert asymmetries.DB_PROFILES_UNHANDLED == {}


def test_db_profile_argument_maps_cover_the_allowlist() -> None:
    # Indexing a profile-keyed map with a missing key is a load-time
    # error, so each map must cover the full 8.4 set. Two maps: postgres
    # enabled_collectors and mysql set_collectors (redis/mongodb drive
    # booleans via ==, which cannot fail on an unknown key).
    maps = ac.db_profile_map_keys()
    assert len(maps) == 2
    for keys in maps:
        assert keys == md.db_profiles()


def test_enrich_blocks_carry_host_and_declared_identity() -> None:
    # Manifest 6.1 requires host on every series (it backs the 13.5
    # provenance guarantee), and manifest 5/10.2.1 promise that a
    # declared identity wins over the synthesized one: database.instance
    # first, the global instance label next, the secret id as fallback.
    blocks = ac.db_enrich_blocks()
    assert set(blocks) == set(ac.db_default_ports())
    declared = (
        'each["__meta_docker_container_label_'
        'ru_3ops_discovery_database_instance"]'
    )
    global_instance = (
        'each["__meta_docker_container_label_ru_3ops_discovery_instance"]'
    )
    for name, body in blocks.items():
        assert 'target_label = "host"' in body, f"enrich_{name}: no host"
        assert "constants.hostname" in body, f"enrich_{name}: no hostname"
        assert declared in body, f"enrich_{name}: database.instance unread"
        assert global_instance in body, f"enrich_{name}: instance unread"


def test_default_ports_match_manifest_table() -> None:
    config_ports = ac.db_default_ports()  # per-pipeline representative type
    manifest_ports = md.db_default_ports()
    for db_type, port in config_ports.items():
        assert manifest_ports[db_type] == port
    # mariadb shares the mysql pipeline, so it has no own config port but
    # must appear in the manifest with the mysql port.
    assert manifest_ports["mariadb"] == manifest_ports["mysql"]
