"""
Manifest 14.1 vs sys.env calls in every config.

The static gate asserts LITERAL defaults inside coalesce(env, default),
never the runtime environment: runtime values are the deployment's
responsibility.
"""

from tests.static import alloy_config as ac
from tests.static import asymmetries
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
        prose, expression = asymmetries.ENV_DEFAULT_EXPRESSIONS.get(
            name, (manifest[name], manifest[name])
        )
        assert manifest[name] == prose
        assert defaults == {expression}, (
            f"{name}: config default {defaults} != manifest {manifest[name]!r}"
        )


def test_default_expressions_are_not_stale() -> None:
    # An entry whose variable now has a literal default (or none) would
    # quietly mask a manifest/config mismatch.
    config = ac.env_defaults()
    for name, (_, expression) in asymmetries.ENV_DEFAULT_EXPRESSIONS.items():
        assert config.get(name) == {expression}


def test_env_scanner_includes_optional_files() -> None:
    # Host-exporter env vars live in an optional file; the both-ways gate
    # relies on the scanner seeing them.
    env = ac.env_defaults()
    assert env["RU_3OPS_DISCOVERY_HOST_ROOTFS_PATH"] == {"/rootfs"}
    assert env["RU_3OPS_DISCOVERY_HOST_PROCFS_PATH"] == {"/host/proc"}
    assert env["RU_3OPS_DISCOVERY_HOST_SYSFS_PATH"] == {"/host/sys"}
