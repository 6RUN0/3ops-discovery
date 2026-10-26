"""
Materialize an Alloy configuration directory for a set of domains.

Alloy merges every *.alloy file of a directory into one component
graph, so composition by domain is done by copying the union of the
chosen domains' files (from ``base/`` and ``optional/``) into one
directory and mounting it as a single volume. Reused by the alloy_check
nox session, the e2e stack fixture and the demo, so all of them exercise
the same composition.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE_DIR = REPO / "implementations/alloy/base"
OPTIONAL_DIR = REPO / "implementations/alloy/optional"

_METRICS_FILES = (
    "010_discovery-scrape.alloy",
    "020_metrics.alloy",
    "090_output-metrics.alloy",
)

#: Domain -> the files a deployment of that domain alone needs. Names are
#: unique across base/ and optional/. Manifest tables 14.4 and 14.4.3
#: carry the same mapping (tests/static/test_domain_files.py).
DOMAIN_FILES: dict[str, tuple[str, ...]] = {
    "metrics": _METRICS_FILES,
    # ipmi is an external exporter scraped by the metrics domain (10.7).
    "ipmi": _METRICS_FILES,
    "database": (
        "010_discovery-scrape.alloy",
        "030_database.alloy",
        "090_output-metrics.alloy",
    ),
    "blackbox": (
        "010_discovery-scrape.alloy",
        "035_blackbox.alloy",
        "090_output-metrics.alloy",
    ),
    "logs": (
        "011_discovery-logs.alloy",
        "040_logs.alloy",
        "050_log-profiles.alloy",
        "091_output-logs.alloy",
    ),
    "otel": (
        "060_otel.alloy",
        "090_output-metrics.alloy",
        "091_output-logs.alloy",
    ),
    "snmp": ("037_snmp.alloy", "090_output-metrics.alloy"),
    "host-metrics": ("070_host-metrics.alloy", "090_output-metrics.alloy"),
    "container-metrics": (
        "075_container-metrics.alloy",
        "090_output-metrics.alloy",
    ),
    "host-logs": ("080_host-logs.alloy", "091_output-logs.alloy"),
}

#: Domains whose union is exactly base/: what `alloy run base/` starts.
DEFAULT_DOMAINS: tuple[str, ...] = (
    "metrics",
    "database",
    "blackbox",
    "logs",
    "ipmi",
)

#: Files using experimental Alloy features (`foreach`); a set containing
#: one needs --stability.level=experimental, any other set must load
#: without it, so the flag cannot mask an experimental block elsewhere.
EXPERIMENTAL_FILES: tuple[str, ...] = ("030_database.alloy",)

#: Combinations validated by the alloy_check session: the default set,
#: all domains without and with snmp (the latter is the merged graph the
#: e2e snmp stack runs), and every domain alone, which proves each
#: domain's file set references nothing outside itself.
COMBOS: dict[str, tuple[str, ...]] = {
    "base": DEFAULT_DOMAINS,
    "all": tuple(d for d in DOMAIN_FILES if d != "snmp"),
    "all-snmp": tuple(DOMAIN_FILES),
    **{f"domain-{d}": (d,) for d in DOMAIN_FILES},
}

#: Files that are NOT *.alloy but without which an overlay cannot load.
#: A top-level local.file is resolved when the graph is built, so a
#: missing path makes the component unhealthy at load time -- `validate`
#: fails, never mind a scrape. The requirement is a property of the
#: overlay, so it is declared here rather than as a branch in whoever
#: materializes a directory (the alloy_check session, the e2e fixture,
#: the demo session).
PROVIDER_FILES: dict[str, tuple[str, ...]] = {
    "037_snmp.alloy": ("snmp_targets.yaml", "snmp_auths.yaml"),
}


def files_for(domains: Iterable[str]) -> tuple[str, ...]:
    """
    Return the sorted union of the chosen domains' file names.

    An unknown domain raises ValueError naming it: a typo such as
    ``log`` for ``logs`` would otherwise yield an incomplete directory.
    """
    names: set[str] = set()
    for domain in domains:
        if domain not in DOMAIN_FILES:
            raise ValueError(
                f"unknown domain {domain!r}; known: {sorted(DOMAIN_FILES)}"
            )
        names.update(DOMAIN_FILES[domain])
    return tuple(sorted(names))


def needs_experimental(domains: Iterable[str]) -> bool:
    """Return True when the domains' files use experimental features."""
    return not set(files_for(domains)).isdisjoint(EXPERIMENTAL_FILES)


def provider_files(files: Iterable[str]) -> tuple[str, ...]:
    """Return the non-.alloy files a chosen set of *.alloy files requires."""
    return tuple(
        name for alloy in files for name in PROVIDER_FILES.get(alloy, ())
    )


def _source(name: str) -> Path:
    """Locate a domain file in base/ or optional/; both is an error."""
    found = [
        d / name for d in (BASE_DIR, OPTIONAL_DIR) if (d / name).is_file()
    ]
    if len(found) > 1:
        raise FileExistsError(
            f"{name} is present in both {BASE_DIR} and {OPTIONAL_DIR}"
        )
    if not found:
        raise FileNotFoundError(
            f"{name} is in neither {BASE_DIR} nor {OPTIONAL_DIR}"
        )
    return found[0]


def materialize(dest: Path, domains: Iterable[str]) -> Path:
    """
    Copy ``files_for(domains)`` into ``dest`` and return it.

    Provider files (PROVIDER_FILES) are the caller's to write; stale ones
    and stale *.alloy files of a previous run are removed first.
    """
    sources = [_source(name) for name in files_for(domains)]
    dest.mkdir(parents=True, exist_ok=True)
    # A reused dest (alloy_check materializes into nox's persistent tmp)
    # must not keep files deleted or deselected since the last run:
    # validate would silently bless a graph that no longer exists.
    stale_names = {p.name for p in dest.glob("*.alloy")}
    stale_names |= {
        name for names in PROVIDER_FILES.values() for name in names
    }
    for name in stale_names:
        (dest / name).unlink(missing_ok=True)
    for src in sources:
        shutil.copy(src, dest / src.name)
    return dest
