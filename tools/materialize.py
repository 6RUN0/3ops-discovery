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
#: base standalone, base + each optional, base + all, and base + all +
#: snmp (the exact merged graph the demo sandbox materializes, so the
#: gate proves 037 composes with every overlay, not just standalone).
_ALL_OVERLAYS = (
    "060_otel.alloy",
    "070_host-metrics.alloy",
    "075_container-metrics.alloy",
    "080_host-logs.alloy",
)
COMBOS: dict[str, tuple[str, ...]] = {
    "base": (),
    "otel": ("060_otel.alloy",),
    "host-metrics": ("070_host-metrics.alloy",),
    "container-metrics": ("075_container-metrics.alloy",),
    "host-logs": ("080_host-logs.alloy",),
    "snmp": ("037_snmp.alloy",),
    "all": _ALL_OVERLAYS,
    "all-snmp": (*_ALL_OVERLAYS, "037_snmp.alloy"),
}

#: Files that are NOT *.alloy but without which an overlay cannot load.
#: A top-level local.file is resolved when the graph is built, so a
#: missing path makes the component unhealthy at load time -- `validate`
#: fails, never mind a scrape. The requirement is a property of the
#: overlay, so it is declared beside the overlay list rather than as a
#: branch in whoever happens to materialize a directory; it used to live
#: in three unconnected places (the alloy_check session, the e2e
#: fixture, the demo session) held together by a comment.
PROVIDER_FILES: dict[str, tuple[str, ...]] = {
    "037_snmp.alloy": ("snmp_targets.yaml", "snmp_auths.yaml"),
}


def provider_files(optional: Iterable[str]) -> tuple[str, ...]:
    """Return the non-.alloy files a chosen set of overlays requires."""
    return tuple(
        name
        for overlay in optional
        for name in PROVIDER_FILES.get(overlay, ())
    )


def materialize(dest: Path, optional: Iterable[str] = ()) -> Path:
    """
    Copy the base config plus the chosen optional files into ``dest``.

    ``optional`` holds file names inside ``alloy-optional/``. A name
    collision with a base file is an error: Alloy would reject the
    merged graph anyway, and failing here names the offending file.
    """
    dest.mkdir(parents=True, exist_ok=True)
    # A reused dest (alloy_check materializes into nox's persistent tmp)
    # must not keep files deleted or deselected since the last run:
    # validate would silently bless a graph that no longer exists.
    stale_names = {*(p.name for p in dest.glob("*.alloy"))}
    stale_names |= {
        name for names in PROVIDER_FILES.values() for name in names
    }
    for name in stale_names:
        (dest / name).unlink(missing_ok=True)
    base_files = sorted(BASE_DIR.glob("*.alloy"))
    if not base_files:
        raise FileNotFoundError(f"no *.alloy files in {BASE_DIR}")
    base_names = {src.name for src in base_files}
    for src in base_files:
        shutil.copy(src, dest / src.name)
    for name in optional:
        # Collision is a name shadowing a base file, not a leftover file
        # in dest (those were just removed).
        if name in base_names:
            raise FileExistsError(
                f"optional file collides with a base file: {name}"
            )
        shutil.copy(OPTIONAL_DIR / name, dest / name)
    return dest
