"""
Contract rules the reference does not meet are recorded, not just prose.

Manifest section 14 promises that every reference-vs-contract gap lives in
asymmetries.py; the 14.4.4 bullet of each unmet rule must point at its
entry, in both languages.
"""

import re

import pytest

from tests.static import asymmetries
from tests.static import manifest_doc as md

_DOCS = ("manifest.ru.md", "manifest.md")


def _rule_section(key: str) -> str:
    return key.split("/", 1)[0]


def test_unmet_rules_name_real_manifest_sections() -> None:
    assert asymmetries.MANIFEST_RULES_UNMET, "table must record 10.3.4/3-4"
    for key in asymmetries.MANIFEST_RULES_UNMET:
        assert _rule_section(key) in md.section_numbers(), key


def test_10_3_4_items_3_and_4_are_recorded() -> None:
    assert "10.3.4/3-4" in asymmetries.MANIFEST_RULES_UNMET


@pytest.mark.parametrize("doc", _DOCS)
def test_reference_bullet_points_at_the_entry(doc: str) -> None:
    text = (md.REPO / "docs" / doc).read_text(encoding="utf-8")
    for key in asymmetries.MANIFEST_RULES_UNMET:
        number = _rule_section(key)
        bullets = re.findall(rf"(?m)^- \[§?{re.escape(number)}\]\(.*$", text)
        # 14.4.4 is the last place a bullet for the section may live.
        assert any("MANIFEST_RULES_UNMET" in b for b in bullets), (
            f"{doc}: no 14.4.4 bullet for {number} names MANIFEST_RULES_UNMET"
        )
