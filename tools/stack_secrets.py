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

from tools import snmp_fixtures
from tools.secret_files import write_secret

#: Fixed SNMPv3 passphrases for the ephemeral e2e/demo snmp-agent.
#:
#: A deliberate, documented exception to the project rule "no secrets in
#: git, not even fakes" -- the pragma below silences detect-secrets, so
#: the reason belongs next to it rather than in a commit message. Unlike
#: the DB credentials (randomised per run), these MUST equal the
#: createUser line of snmp-agent/snmpd.conf, which is baked into the
#: image at build time: both sides need the value before either process
#: starts, so there is no run to generate it in. Throwaway values for a
#: local agent holding no data, torn down with the stack.
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

    write_secret(
        secrets_dir / "postgres-orders.dsn",
        f"postgresql://{user}:{pg_pw}@postgres:5432/postgres?sslmode=disable",
    )
    # Second postgres instance on the basic-v1 profile: the e2e proves
    # the profile shrinks the exporter's collection scope against the
    # extended-v1 postgres-orders control. Same generated credentials,
    # different server (compose service postgres-basic).
    write_secret(
        secrets_dir / "postgres-audit.dsn",
        f"postgresql://{user}:{pg_pw}@postgres-basic:5432/postgres"
        "?sslmode=disable",
    )
    # go-sql-driver DSN; root, no database (trailing slash).
    write_secret(
        secrets_dir / "mariadb-billing.dsn", f"root:{my_pw}@(mariadb:3306)/"
    )
    # redis_addr cannot take a Secret, so the address (host:port) lives in
    # .dsn (non-secret) and the password in .redispass (manifest 9).
    write_secret(secrets_dir / "redis-cache.dsn", "redis:6379")
    write_secret(secrets_dir / "redis-cache.redispass", redis_pw)
    write_secret(
        secrets_dir / "mongodb-docs.dsn",
        f"mongodb://{user}:{mongo_pw}@mongodb:27017",
    )
    # SNMP auth secret for the file-provider domain (overlay 037). Not a .dsn:
    # the exporter reads it as inline `config` via local.file is_secret. The
    # netmon-v3 creds MUST equal the snmp-agent snmpd.conf (v3 authPriv,
    # SHA/AES). Path is fixed by convention (RU_3OPS_DISCOVERY_SECRETS_DIR),
    # so no env var is returned for it.
    auths = {
        "netmon-v3": {
            "version": snmp_fixtures.SNMP_V3,
            "username": "netmon",
            "security_level": "authPriv",
            "password": _SNMP_AUTH_PASS,
            "auth_protocol": "SHA",
            "priv_protocol": "AES",
            "priv_password": _SNMP_PRIV_PASS,
        }
    }
    # This is the only real auth profile the repository produces, so it is
    # also the only place the contract's control point can actually fire.
    snmp_fixtures.validate_auths(auths)
    write_secret(
        secrets_dir / "snmp_auths.yaml",
        yaml.safe_dump({"auths": auths}, sort_keys=False),
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
