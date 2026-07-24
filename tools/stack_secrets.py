"""
DB credential materialization for the e2e stack and the demo sandbox.

One credential source per database service: each .dsn file and the matching
container env come from the same generated password. The DSN host is the
compose service name. Per-type content format is fixed by manifest section 9.
Reused by tests/e2e/conftest.py and the nox `demo` session.
"""

from __future__ import annotations

import secrets as pysecrets
from pathlib import Path


def write_secrets(secrets_dir: Path) -> dict[str, str]:
    """Generate DB secret files under ``secrets_dir``; return the env map."""
    secrets_dir.mkdir(parents=True, exist_ok=True)
    pg_pw = pysecrets.token_hex(16)
    my_pw = pysecrets.token_hex(16)
    redis_pw = pysecrets.token_hex(16)
    mongo_pw = pysecrets.token_hex(16)
    user = "xad_e2e"

    (secrets_dir / "postgres-orders.dsn").write_text(
        f"postgresql://{user}:{pg_pw}@postgres:5432/postgres?sslmode=disable",
        encoding="ascii",
    )
    # go-sql-driver DSN; root, no database (trailing slash).
    (secrets_dir / "mariadb-billing.dsn").write_text(
        f"root:{my_pw}@(mariadb:3306)/", encoding="ascii"
    )
    # redis_addr cannot take a Secret, so the address (host:port) lives in
    # .dsn (non-secret) and the password in .redispass (manifest 9).
    (secrets_dir / "redis-cache.dsn").write_text(
        "redis:6379", encoding="ascii"
    )
    (secrets_dir / "redis-cache.redispass").write_text(
        redis_pw, encoding="ascii"
    )
    (secrets_dir / "mongodb-docs.dsn").write_text(
        f"mongodb://{user}:{mongo_pw}@mongodb:27017", encoding="ascii"
    )
    return {
        "RU_3OPS_DISCOVERY_E2E_PG_USER": user,
        "RU_3OPS_DISCOVERY_E2E_PG_PASSWORD": pg_pw,
        "RU_3OPS_DISCOVERY_E2E_MARIADB_PASSWORD": my_pw,
        "RU_3OPS_DISCOVERY_E2E_REDIS_PASSWORD": redis_pw,
        "RU_3OPS_DISCOVERY_E2E_MONGO_USER": user,
        "RU_3OPS_DISCOVERY_E2E_MONGO_PASSWORD": mongo_pw,
    }
