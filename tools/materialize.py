"""
Materialize an Alloy configuration directory.

Alloy merges every *.alloy file of a directory into one component
graph, so "base + optional files" composition is done by copying the
chosen files into a temporary directory and mounting it as a single
volume. Reused by the alloy_check nox session
and by the e2e stack fixture, so both gates exercise the same overlay
mechanism.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE_DIR = REPO / "alloy"
OPTIONAL_DIR = REPO / "alloy-optional"

#: Directory combinations validated by the alloy_check session:
#: base standalone, base + each optional, base + all.
COMBOS: dict[str, tuple[str, ...]] = {
    "base": (),
    "otel": ("060_otel.alloy",),
    "host-metrics": ("070_host-metrics.alloy",),
    "host-logs": ("080_host-logs.alloy",),
    "snmp": ("037_snmp.alloy",),
    "all": (
        "060_otel.alloy",
        "070_host-metrics.alloy",
        "080_host-logs.alloy",
    ),
}


def materialize(dest: Path, optional: Iterable[str] = ()) -> Path:
    """
    Copy the base config plus the chosen optional files into ``dest``.

    ``optional`` holds file names inside ``alloy-optional/``. A name
    collision with a base file is an error: Alloy would reject the
    merged graph anyway, and failing here names the offending file.
    """
    dest.mkdir(parents=True, exist_ok=True)
    base_files = sorted(BASE_DIR.glob("*.alloy"))
    if not base_files:
        raise FileNotFoundError(f"no *.alloy files in {BASE_DIR}")
    base_names = {src.name for src in base_files}
    for src in base_files:
        shutil.copy(src, dest / src.name)
    for name in optional:
        # Collision is a name shadowing a base file, not a leftover file in
        # a reused dest (alloy_check materializes into nox's persistent tmp,
        # so the check must be against the base set, not dest contents).
        if name in base_names:
            raise FileExistsError(
                f"optional file collides with a base file: {name}"
            )
        shutil.copy(OPTIONAL_DIR / name, dest / name)
    return dest
