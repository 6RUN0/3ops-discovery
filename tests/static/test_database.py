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


def test_db_profiles_are_a_documented_asymmetry() -> None:
    assert md.db_profiles() == set(asymmetries.DB_PROFILES_UNHANDLED)


def test_default_ports_match_manifest_table() -> None:
    config_ports = ac.db_default_ports()  # per-pipeline representative type
    manifest_ports = md.db_default_ports()
    for db_type, port in config_ports.items():
        assert manifest_ports[db_type] == port
    # mariadb shares the mysql pipeline, so it has no own config port but
    # must appear in the manifest with the mysql port.
    assert manifest_ports["mariadb"] == manifest_ports["mysql"]
