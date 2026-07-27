"""
Every intra-repo markdown link resolves: file paths and #fragments.

rumdl checks markdown structure and lychee checks external URLs, but
neither validates that a `#fragment` matches a real heading anchor, so
a renamed heading would silently break every reference to it. This
gate resolves all relative links in the repo's markdown files against
the tree and the target file's GitHub-style heading slugs.
"""

from pathlib import Path

from tests.static import doc_links as dl


def test_slugify_matches_github_anchors() -> None:
    # Pinned against anchors GitHub actually generates for the
    # manifest's own headings (the pre-existing intra-doc links).
    assert dl.slugify("9. Secret contract") == "9-secret-contract"
    assert (
        dl.slugify("6.1. Labels, добавляемые Alloy")
        == "61-labels-добавляемые-alloy"
    )
    assert dl.slugify("10.3.2. `logs.profile`") == "1032-logsprofile"


def test_checker_flags_broken_fragment_and_path(tmp_path: Path) -> None:
    md = tmp_path / "doc.md"
    md.write_text(
        "## 1. Введение\n\n"
        "ok: [сюда](#1-введение)\n"
        "bad anchor: [туда](#2-нет-такого)\n"
        "bad path: [файл](missing/file.md)\n"
        "```\n[в коде](#игнорируется)\n```\n",
        encoding="utf-8",
    )
    broken = dl.broken_links(md)
    assert "#2-нет-такого" in broken
    assert "missing/file.md" in broken
    assert len(broken) == 2


def test_repo_markdown_links_resolve() -> None:
    for md in dl.markdown_files():
        assert dl.broken_links(md) == [], f"broken links in {md}"


def test_checker_flags_a_section_number_spilling_out_of_a_link(
    tmp_path: Path,
) -> None:
    # The exact defect this check exists for, as it shipped in the
    # changelog: the reader sees "§10.x" but only "§1" is clickable and
    # it lands on section 1. Both links resolve, so broken_links -- which
    # only asks whether an anchor exists -- stays silent on it.
    md = tmp_path / "doc.md"
    md.write_text(
        "## 10. Домены\n\n"
        "shipped defect: [§1](#10-домены)0.x\n"
        "fine: [§10](#10-домены), and a sentence ending in "
        "[§10](#10-домены).\n",
        encoding="utf-8",
    )
    assert dl.spilled_section_links(md) == ["[§1](#10-домены)"]
    assert dl.broken_links(md) == []


def test_links_quoted_as_inline_code_are_not_checked(tmp_path: Path) -> None:
    # The changelog quotes a broken link on purpose to describe the
    # defect a gate catches. Backticked markdown is never rendered, so
    # it is documentation, not a reference -- while a heading titled
    # entirely in backticks must keep its anchor (manifest 5 does that).
    md = tmp_path / "doc.md"
    md.write_text(
        "### `ru.3ops.discovery.enabled`\n\n"
        "quoted defect: `[§1](#1-purpose)0.x` is what went wrong\n"
        "quoted dead link: `[x](no/such.md)`\n"
        "real link: [here](#ru3opsdiscoveryenabled)\n",
        encoding="utf-8",
    )
    assert dl.broken_links(md) == []
    assert dl.spilled_section_links(md) == []
    assert "ru3opsdiscoveryenabled" in dl.heading_slugs(md)


def test_no_section_number_spills_out_of_a_link() -> None:
    for md in dl.markdown_files():
        assert dl.spilled_section_links(md) == [], (
            f"a section number continues past the link in {md}"
        )
