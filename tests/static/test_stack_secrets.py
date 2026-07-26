"""tools.stack_secrets: DB credential materialization."""

from pathlib import Path

from tools.stack_secrets import write_secrets


def test_write_secrets_creates_all_dsn_files(tmp_path: Path) -> None:
    env = write_secrets(tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {
        "postgres-orders.dsn",
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
