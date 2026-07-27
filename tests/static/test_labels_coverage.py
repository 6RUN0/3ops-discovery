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


def _documented_labels() -> set[str]:
    labels: set[str] = set()
    for number in md.labels_sections():
        labels |= md.domain_label_names(number)
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
    ghosts = unread - documented
    assert not ghosts, (
        f"LABELS_UNREAD entries missing from every labels table: {ghosts}"
    )


def test_every_domain_with_labels_is_covered() -> None:
    # The gate used to read a hand-kept tuple of five sections, and the
    # ipmi domain (10.7.1) was written without being added to it -- five
    # documented labels that no direction of the check ever saw. The list
    # now comes from the manifest, so this asserts the derivation itself:
    # every 10.x domain that has a Labels subsection is in it.
    covered = set(md.labels_sections())
    domains = set(
        re.findall(
            r"(?m)^### (10\.\d+)\. Domain: ",
            md.MANIFEST.read_text(encoding="utf-8"),
        )
    )
    missing = {
        domain
        for domain in domains
        if not any(number.startswith(f"{domain}.") for number in covered)
    }
    # 10.6 (snmp) is the one domain not driven by Docker labels: its
    # targets come from a file, so it has no labels subsection to cover.
    assert missing == {"10.6"}, f"domains without a labels section: {missing}"
