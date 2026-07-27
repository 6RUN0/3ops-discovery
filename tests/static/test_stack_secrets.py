"""tools.stack_secrets: DB credential materialization."""

import stat
from pathlib import Path

from tools import snmp_fixtures
from tools.secret_files import is_owner_only
from tools.stack_secrets import write_secrets


def test_write_secrets_creates_all_dsn_files(tmp_path: Path) -> None:
    env = write_secrets(tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {
        "postgres-orders.dsn",
        "postgres-audit.dsn",
        "mariadb-billing.dsn",
        "redis-cache.dsn",
        "redis-cache.redispass",
        "mongodb-docs.dsn",
        "snmp_auths.yaml",
    }
    # DSN hosts are compose service names; env keys drive the containers.
    assert "@postgres:5432" in (tmp_path / "postgres-orders.dsn").read_text()
    assert (tmp_path / "redis-cache.dsn").read_text() == "redis:6379"
    assert env["RU_3OPS_DISCOVERY_E2E_PG_USER"] == "xad_e2e"
    assert set(env) == {
        "RU_3OPS_DISCOVERY_E2E_PG_USER",
        "RU_3OPS_DISCOVERY_E2E_PG_PASSWORD",
        "RU_3OPS_DISCOVERY_E2E_MARIADB_PASSWORD",
        "RU_3OPS_DISCOVERY_E2E_REDIS_PASSWORD",
        "RU_3OPS_DISCOVERY_E2E_MONGO_USER",
        "RU_3OPS_DISCOVERY_E2E_MONGO_PASSWORD",
    }


def test_generated_secrets_are_readable_by_their_owner_alone(
    tmp_path: Path,
) -> None:
    # Manifest 9 asks for exactly this, and it was the one clause of the
    # section no gate covered. It matters beyond the ephemeral e2e run:
    # `nox -s demo` leaves .demo/secrets/*.dsn in the working tree, so a
    # 0644 default outlives the sandbox that produced it.
    write_secrets(tmp_path)
    written = sorted(tmp_path.iterdir())
    assert written, "no secret files written"
    for path in written:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert is_owner_only(path), f"{path.name} is mode {mode:o}, not 0600"


def test_snmp_fixture_secrets_are_owner_only(tmp_path: Path) -> None:
    # The second writer of the same secret directory. Whichever entry
    # point a run takes, the mode has to be the same one.
    config_dir = tmp_path / "config"
    secrets_dir = tmp_path / "secrets"
    snmp_fixtures.write_snmp_fixtures(
        config_dir,
        secrets_dir,
        devices=[{"address": "127.0.0.1", "module": "system", "auth": "a"}],
        auths={
            "a": {
                "version": snmp_fixtures.SNMP_V2C,
                "community": "public",  # pragma: allowlist secret
            }
        },
    )
    assert is_owner_only(secrets_dir / "snmp_auths.yaml")
    # The device inventory is not a secret and is not claimed to be one:
    # it names addresses and modules, never credentials (manifest 10.6).
    assert (config_dir / "snmp_targets.yaml").exists()
