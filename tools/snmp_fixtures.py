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
    loader, so native ints (``version: 3``) are correct there.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "snmp_targets.yaml").write_text(
        yaml.safe_dump(devices, sort_keys=False), encoding="utf-8"
    )
    (secrets_dir / "snmp_auths.yaml").write_text(
        yaml.safe_dump({"auths": auths}, sort_keys=False), encoding="utf-8"
    )
