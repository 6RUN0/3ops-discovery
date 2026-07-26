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

import yaml

#: Fixed SNMPv3 passphrases for the ephemeral e2e/demo snmp-agent. Unlike the
#: DB credentials (randomised per run), these MUST equal the static
#: snmp-agent/snmpd.conf createUser line, so they are constants, not
#: token_hex. Throwaway test values for a local agent, never real secrets.
_SNMP_AUTH_PASS = "netmon-auth-pass"  # pragma: allowlist secret
_SNMP_PRIV_PASS = "netmon-priv-pass"  # pragma: allowlist secret


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
    # SNMP auth secret for the file-provider domain (overlay 037). Not a .dsn:
    # the exporter reads it as inline `config` via local.file is_secret. The
    # netmon-v3 creds MUST equal the snmp-agent snmpd.conf (v3 authPriv,
    # SHA/AES). Path is fixed by convention (RU_3OPS_DISCOVERY_SECRETS_DIR),
    # so no env var is returned for it.
    (secrets_dir / "snmp_auths.yaml").write_text(
        yaml.safe_dump(
            {
                "auths": {
                    "netmon-v3": {
                        "version": 3,
                        "username": "netmon",
                        "security_level": "authPriv",
                        "password": _SNMP_AUTH_PASS,
                        "auth_protocol": "SHA",
                        "priv_protocol": "AES",
                        "priv_password": _SNMP_PRIV_PASS,
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return {
        "RU_3OPS_DISCOVERY_E2E_PG_USER": user,
        "RU_3OPS_DISCOVERY_E2E_PG_PASSWORD": pg_pw,
        "RU_3OPS_DISCOVERY_E2E_MARIADB_PASSWORD": my_pw,
        "RU_3OPS_DISCOVERY_E2E_REDIS_PASSWORD": redis_pw,
        "RU_3OPS_DISCOVERY_E2E_MONGO_USER": user,
        "RU_3OPS_DISCOVERY_E2E_MONGO_PASSWORD": mongo_pw,
    }
