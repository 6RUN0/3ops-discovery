"""
Manifest 10.x labels tables vs the reference config.

Every documented discovery label must be read by the config, or be
listed in asymmetries.LABELS_UNREAD with a reason. Both directions are
enforced: an undocumented unread label fails, and so does a stale
LABELS_UNREAD entry once the config starts reading the label (or the
manifest stops documenting it).
"""

import re

from tests.static import alloy_config as ac
from tests.static import asymmetries
from tests.static import manifest_doc as md

LABELS_TABLE_SECTIONS = ("10.1.1", "10.2.1", "10.3.5", "10.4.1", "10.5.1")


def _documented_labels() -> dict[str, bool]:
    labels: dict[str, bool] = {}
    for number in LABELS_TABLE_SECTIONS:
        labels |= md.domain_labels(number)
    return labels


def _meta_form(label: str) -> str:
    """Docker service-discovery meta label for a contract label name."""
    suffix = label.removeprefix("ru.3ops.discovery.")
    return "__meta_docker_container_label_ru_3ops_discovery_" + re.sub(
        r"[.-]", "_", suffix
    )


def test_documented_labels_read_or_documented_gap() -> None:
    text = ac.config_text()
    documented = _documented_labels()
    unread = set(asymmetries.LABELS_UNREAD)
    for label in documented:
        if label in unread:
            assert _meta_form(label) not in text, (
                f"{label}: stale LABELS_UNREAD entry, the config reads it"
            )
        else:
            assert _meta_form(label) in text, (
                f"{label}: documented but never read; wire it up or add "
                "a LABELS_UNREAD entry with a reason"
            )
    ghosts = unread - set(documented)
    assert not ghosts, (
        f"LABELS_UNREAD entries missing from every labels table: {ghosts}"
    )
