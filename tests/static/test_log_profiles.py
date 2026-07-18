"""Manifest 8.3 vs 040/050."""

from tests.static import alloy_config as ac
from tests.static import asymmetries
from tests.static import manifest_doc as md


def test_allowlist_is_subset_of_manifest() -> None:
    assert ac.log_profile_allowlist() <= md.log_profiles()


def test_asymmetry_table_is_exact() -> None:
    unimplemented = md.log_profiles() - ac.log_profile_allowlist()
    assert unimplemented == set(asymmetries.LOG_PROFILES_UNIMPLEMENTED)


def test_dispatcher_covers_allowlist_except_raw_passthrough() -> None:
    # raw-v1 is a pass-through by design; mixed-v1 maps to one or MORE
    # stages, so sets (not counts) are compared.
    expected = ac.log_profile_allowlist() - {"raw-v1"}
    assert ac.dispatcher_profiles() == expected
