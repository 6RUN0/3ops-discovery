"""Every intra-repo markdown link resolves: file paths and #fragments.

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
