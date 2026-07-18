"""
Manifest 14.1 vs sys.env calls in every config.

The static gate asserts LITERAL defaults inside coalesce(env, default),
never the runtime environment: runtime values are the deployment's
responsibility.
"""

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md


def test_every_env_call_has_a_literal_default() -> None:
    assert ac.env_calls_without_default() == set()


def test_env_table_matches_config_both_ways() -> None:
    assert set(md.env_defaults()) == set(ac.env_defaults())


def test_defaults_agree_and_are_consistent_across_files() -> None:
    manifest = md.env_defaults()
    for name, defaults in ac.env_defaults().items():
        assert len(defaults) == 1, (
            f"{name} has diverging defaults across files: {defaults}"
        )
        assert defaults == {manifest[name]}, (
            f"{name}: config default {defaults} != manifest {manifest[name]!r}"
        )
