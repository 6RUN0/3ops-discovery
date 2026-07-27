"""
Single source of truth for provisioning the SNMP device + auth files.

The domain is the only file-provider domain: `037_snmp.alloy` reads a device
list and an auth secret from disk. Neither file is committed (the auth file is
a secret, like `.dsn`), so every runtime that loads 037 -- `alloy_check`
(empty stubs), the e2e fixture (real device + creds), and `demo` -- writes
them here. Keeping the writer in one place is the M-B "single source" fix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

#: Wire values of the `version` field: the exporter takes an int, not the
#: `v2c`/`v3` spelling used in prose (manifest 10.6.1).
SNMP_V2C = 2
SNMP_V3 = 3

#: Contract allowlist (manifest 10.6.1). The exporter itself accepts 1..3;
#: SNMPv1 is excluded by the contract, so the fixture must never carry it.
SNMP_VERSIONS = frozenset({SNMP_V2C, SNMP_V3})

#: Enums of snmp_exporter v0.29.0 (`config/config.go`, struct `Auth`).
SECURITY_LEVELS = frozenset({"noAuthNoPriv", "authNoPriv", "authPriv"})
AUTH_PROTOCOLS = frozenset(
    {"MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"}
)
PRIV_PROTOCOLS = frozenset(
    {"DES", "AES", "AES192", "AES192C", "AES256", "AES256C"}
)

#: Fields each security level makes mandatory, on top of `username`.
#: Pinned against manifest 10.6.1 by a static gate.
REQUIRED_FIELDS_BY_LEVEL = {
    "noAuthNoPriv": (),
    "authNoPriv": ("password", "auth_protocol"),
    "authPriv": (
        "password",
        "auth_protocol",
        "priv_password",
        "priv_protocol",
    ),
}


def _validate_profile(name: str, profile: Any) -> None:
    if not isinstance(profile, dict):
        raise TypeError(f"snmp auth {name!r}: profile must be a mapping")
    version = profile.get("version")
    # `2.0` equals 2 in a set lookup but the exporter's typed loader rejects
    # a float, so the wire type has to be checked, not just the value.
    if type(version) is not int or version not in SNMP_VERSIONS:
        raise ValueError(
            f"snmp auth {name!r}: version {version!r} outside the contract "
            f"allowlist {sorted(SNMP_VERSIONS)} (2 = v2c, 3 = v3)"
        )
    # Enum membership does not depend on the version branch: a v2c profile
    # carrying a bogus auth_protocol is still a malformed profile.
    for field, allowed in (
        ("auth_protocol", AUTH_PROTOCOLS),
        ("priv_protocol", PRIV_PROTOCOLS),
    ):
        value = profile.get(field)
        if value is not None and value not in allowed:
            raise ValueError(
                f"snmp auth {name!r}: {field} {value!r} not in "
                f"{sorted(allowed)}"
            )
    if version == SNMP_V2C:
        if not profile.get("community"):
            raise ValueError(f"snmp auth {name!r}: v2c requires community")
        return
    if not profile.get("username"):
        raise ValueError(f"snmp auth {name!r}: v3 requires username")
    level = profile.get("security_level")
    if level not in SECURITY_LEVELS:
        raise ValueError(
            f"snmp auth {name!r}: security_level {level!r} not in "
            f"{sorted(SECURITY_LEVELS)}"
        )
    for field in REQUIRED_FIELDS_BY_LEVEL[level]:
        if not profile.get(field):
            raise ValueError(
                f"snmp auth {name!r}: security_level {level} requires {field}"
            )


def validate_auths(auths: dict[str, Any]) -> None:
    """
    Check the auth profiles against manifest 10.6.1.

    The contract calls this the repository's single control point for the
    auth file: Alloy never inspects the secret (the exporter parses it), so
    a malformed or out-of-allowlist profile would otherwise only surface as
    a scrape-time error against real hardware.

    Raises ``ValueError`` for a profile that breaks the contract and
    ``TypeError`` for one that is not a mapping at all.
    """
    for name, profile in auths.items():
        _validate_profile(name, profile)


def write_snmp_fixtures(
    config_dir: Path,
    secrets_dir: Path,
    *,
    devices: list[dict[str, str]],
    auths: dict[str, Any],
) -> None:
    """
    Write the device file and the auth secret to disk.

    The device file lands in ``config_dir``, the auth secret in
    ``secrets_dir``. ``devices`` values must all be strings (the device file
    is decoded by
    ``encoding.from_yaml``, which would otherwise produce non-string scalars).
    ``auths`` is the ``auths:`` map body; it is parsed by the exporter's typed
    loader, so native ints (``version: 3``) are correct there. It is validated
    against manifest 10.6.1 before anything is written.
    """
    validate_auths(auths)
    config_dir.mkdir(parents=True, exist_ok=True)
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "snmp_targets.yaml").write_text(
        yaml.safe_dump(devices, sort_keys=False), encoding="utf-8"
    )
    (secrets_dir / "snmp_auths.yaml").write_text(
        yaml.safe_dump({"auths": auths}, sort_keys=False), encoding="utf-8"
    )
