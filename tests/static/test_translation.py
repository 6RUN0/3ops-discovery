"""
Translations stay structurally isomorphic to their Russian originals.

The manifest is Russian by design and every anchor-based gate reads
docs/manifest.ru.md alone, so docs/manifest.md is normatively invisible:
no other check would notice it going stale. This gate binds the pair by
structure -- see tests/static/translation.py for what the skeleton
covers and what it deliberately cannot (the prose itself).
"""

from pathlib import Path

import pytest

from tests.static import asymmetries
from tests.static import translation as tr


@pytest.mark.parametrize(("ru", "en"), tr.PAIRS)
def test_both_sides_of_the_pair_exist(ru: str, en: str) -> None:
    assert (tr.ROOT / ru).is_file(), f"{ru} is missing"
    assert (tr.ROOT / en).is_file(), f"{en} is missing"


@pytest.mark.parametrize(("ru", "en"), tr.PAIRS)
def test_heading_structure_matches(ru: str, en: str) -> None:
    original = tr.skeleton(tr.ROOT / ru)
    translated = tr.skeleton(tr.ROOT / en)
    assert translated.heading_levels == original.heading_levels, (
        f"{en}: heading nesting diverged from {ru}"
    )
    assert translated.section_numbers == original.section_numbers, (
        f"{en}: section numbering diverged from {ru}"
    )


@pytest.mark.parametrize(("ru", "en"), tr.PAIRS)
def test_code_blocks_match(ru: str, en: str) -> None:
    # Code blocks carry the normative payload -- label examples, profile
    # tables, the regex. A dropped block is a dropped requirement.
    original = tr.skeleton(tr.ROOT / ru)
    translated = tr.skeleton(tr.ROOT / en)
    assert translated.fence_languages == original.fence_languages, (
        f"{en}: code blocks diverged from {ru}"
    )


@pytest.mark.parametrize(("ru", "en"), tr.PAIRS)
def test_list_items_match(ru: str, en: str) -> None:
    original = tr.skeleton(tr.ROOT / ru)
    translated = tr.skeleton(tr.ROOT / en)
    assert translated.list_items == original.list_items, (
        f"{en}: list item count diverged from {ru}"
    )


@pytest.mark.parametrize(("ru", "en"), tr.PAIRS)
def test_table_rows_match_within_the_declared_asymmetry(
    ru: str, en: str
) -> None:
    original = tr.skeleton(tr.ROOT / ru)
    translated = tr.skeleton(tr.ROOT / en)
    declared = asymmetries.TRANSLATION_EXTRA_TABLE_ROWS.get(en, 0)
    assert translated.table_rows - original.table_rows == declared, (
        f"{en}: table rows differ from {ru} by "
        f"{translated.table_rows - original.table_rows}, "
        f"TRANSLATION_EXTRA_TABLE_ROWS declares {declared}"
    )


def test_extra_table_row_entries_name_a_real_translation() -> None:
    # Exact-equality above already retires a phantom count; this retires
    # a phantom FILE, which would otherwise sit in the table forever.
    translated = {en for _, en in tr.PAIRS}
    unknown = set(asymmetries.TRANSLATION_EXTRA_TABLE_ROWS) - translated
    assert unknown == set(), (
        f"dead TRANSLATION_EXTRA_TABLE_ROWS keys: {unknown}"
    )


def test_manifest_translation_declares_itself_non_normative() -> None:
    # The whole reason the pair is allowed to exist: a reader must not
    # mistake the translation for the contract the gates enforce.
    header = (tr.ROOT / "docs/manifest.md").read_text(encoding="utf-8")
    header = header[: header.index("## 1.")]
    assert "(manifest.ru.md)" in header, (
        "the manifest translation must link its normative original"
    )
    assert "normative" in header


def test_skeleton_detects_a_dropped_section(tmp_path: Path) -> None:
    # The checker itself, unit-tested so it cannot rot into a no-op.
    original = tmp_path / "ru.md"
    original.write_text(
        "# T\n\n## 1. Раз\n\n```yaml\na: b\n```\n\n## 2. Два\n\n- пункт\n",
        encoding="utf-8",
    )
    faithful = tmp_path / "ok.md"
    faithful.write_text(
        "# T\n\n## 1. One\n\n```yaml\na: b\n```\n\n## 2. Two\n\n- item\n",
        encoding="utf-8",
    )
    lossy = tmp_path / "bad.md"
    lossy.write_text(
        "# T\n\n## 1. One\n\n```yaml\na: b\n```\n",
        encoding="utf-8",
    )
    assert tr.skeleton(faithful) == tr.skeleton(original)
    assert tr.skeleton(lossy) != tr.skeleton(original)
    assert tr.skeleton(original).section_numbers == ("1", "2")
    assert tr.skeleton(original).fence_languages == ("yaml",)
