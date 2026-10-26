"""
Neutrality gate: the contract must not name its reference implementation.

Counts implementation-specific tokens (Alloy, its component names, River
functions) per manifest section outside the reference-implementation
section 14.4. Sections that still mention them are listed in
asymmetries.MANIFEST_IMPLEMENTATION_MENTIONS; the table only shrinks.
"""

from tests.static import asymmetries
from tests.static import manifest_doc as md


def test_tokens_stay_in_sections_the_table_allows() -> None:
    found = set(md.implementation_mentions())
    allowed = set(asymmetries.MANIFEST_IMPLEMENTATION_MENTIONS)
    assert found - allowed == set(), (
        f"new implementation mentions: {found - allowed}"
    )
    assert allowed - found == set(), f"phantom exemptions: {allowed - found}"


def test_translation_stays_within_the_table() -> None:
    en = (md.REPO / "docs" / "manifest.md").read_text(encoding="utf-8")
    extra = set(md.implementation_mentions(en)) - set(
        asymmetries.MANIFEST_IMPLEMENTATION_MENTIONS
    )
    assert extra == set(), f"docs/manifest.md mentions the agent in {extra}"


def test_token_scanner_counts_components_and_skips_the_reference() -> None:
    text = (
        "## 8. Profiles\n\ncall `prometheus.scrape` and Alloy\n\n"
        "## 14. Impl\n\n| `X` | `/etc/alloy/snmp_targets.yaml` |\n\n"
        "### 14.4. Reference\n\n`discovery.docker`\n\n"
        "#### 14.4.1. Кастомизация\n\n`foreach`\n"
    )
    assert md.implementation_mentions(text) == {"8": 2}


def test_unnumbered_subheading_belongs_to_the_enclosing_section() -> None:
    text = "## 5. X\n\n### `a`\n\nAlloy\n"
    assert md.implementation_mentions(text) == {"5": 1}


def test_unnumbered_subheading_under_the_reference_is_skipped() -> None:
    text = "### 14.4. Reference\n\n#### `a`\n\nAlloy\n\n## 15. Y\n\nAlloy\n"
    assert md.implementation_mentions(text) == {"15": 1}
