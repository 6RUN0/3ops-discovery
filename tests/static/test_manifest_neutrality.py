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
    found = set(md.implementation_mentions(en))
    allowed = set(asymmetries.MANIFEST_IMPLEMENTATION_MENTIONS)
    assert found == allowed, (
        f"docs/manifest.md: extra {found - allowed}, missing {allowed - found}"
    )


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


def test_mentions_of_one_section_add_up_across_its_subheadings() -> None:
    text = "## 5. X\n\nAlloy\n\n### `a`\n\nAlloy and foreach\n"
    assert md.implementation_mentions(text) == {"5": 3}


def test_text_before_the_first_numbered_heading_is_skipped() -> None:
    text = "# Title\n\nAlloy\n\n## Preface\n\nAlloy\n\n## 1. A\n\nAlloy\n"
    assert md.implementation_mentions(text) == {"1": 1}


def test_scanner_knows_relabel_and_river_vocabulary() -> None:
    for token in (
        "`prometheus.relabel`",
        "`loki.relabel`",
        "`discovery.file`",
        "`source_labels`",
        "`target_label`",
        "`__address__`",
        "River",
        "`stability.level`",
        "run alloy here",
        "vmagent",
        "`keep_if_equal`",
        "`docker_sd_configs`",
    ):
        text = f"## 5. X\n\n{token}\n"
        assert md.implementation_mentions(text) == {"5": 1}, token


def test_scanner_ignores_contract_paths_and_label_names() -> None:
    text = (
        "## 5. X\n\n`/etc/alloy/x.yaml` `ru.3ops.discovery.version` "
        "x-alloy-discovery\n"
    )
    assert md.implementation_mentions(text) == {}
