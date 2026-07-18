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


def test_default_ports_are_the_type_standards() -> None:
    # Config-internal invariant until the manifest gains a port table
    # in 10.2 (phase 2): 10.2.1 says only "standard port of
    # the type", so the numbers have no manifest anchor yet.
    standard_ports = {"postgres": "5432"}
    assert ac.db_default_ports() == standard_ports
