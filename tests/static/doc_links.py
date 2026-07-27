"""
Markdown link extraction and GitHub-style anchor resolution.

Backs test_doc_links: collects the repo's markdown files, computes the
heading slugs GitHub generates for them, and resolves every relative
link (path and optional #fragment) against the tree.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_EXTERNAL = ("http://", "https://", "mailto:")
_FENCE = re.compile(r"(?ms)^```.*?^```$")
#: Inline code spans. A link inside backticks is shown to the reader as
#: literal markdown, never rendered, so it is not a link to resolve --
#: the changelog quotes broken ones on purpose.
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_HEADING = re.compile(r"(?m)^#{1,6} (.+)$")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
#: A link immediately followed by a digit: the section number the reader
#: sees continues OUTSIDE the link, so only its prefix is clickable.
_SPILLED = re.compile(r"\[[^\]]*\]\([^)\s]+\)(?=[0-9])")


def markdown_files() -> list[Path]:
    """Repo markdown files covered by the gate (root and docs/)."""
    return sorted([*ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md")])


def slugify(heading: str, seen: dict[str, int] | None = None) -> str:
    """GitHub anchor for a heading; ``seen`` dedups repeated headings."""
    slug = heading.replace("`", "").lower()
    slug = re.sub(r"[^\w\s-]", "", slug).replace(" ", "-")
    if seen is not None:
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        if count:
            slug = f"{slug}-{count}"
    return slug


def _prose(md_text: str) -> str:
    return _FENCE.sub("", md_text)


def _linkable(md_text: str) -> str:
    """
    Prose with inline code dropped too -- headings must keep theirs.

    Section 5 of the manifest titles its headings with a bare label name
    in backticks, so stripping inline code before _HEADING would erase
    those anchors entirely. Only link extraction may use this.
    """
    return _INLINE_CODE.sub("", _prose(md_text))


def heading_slugs(md_path: Path) -> set[str]:
    """All heading anchors of a markdown file."""
    seen: dict[str, int] = {}
    prose = _prose(md_path.read_text(encoding="utf-8"))
    return {slugify(h, seen) for h in _HEADING.findall(prose)}


def spilled_section_links(md_path: Path) -> list[str]:
    """Links a section number runs past: `[1](#1-x)0.x` reads as 10.x."""
    text = _linkable(md_path.read_text(encoding="utf-8"))
    return [match.group(0) for match in _SPILLED.finditer(text)]


def broken_links(md_path: Path) -> list[str]:
    """Relative link targets that do not resolve (path or fragment)."""
    broken: list[str] = []
    for target in _LINK.findall(
        _linkable(md_path.read_text(encoding="utf-8"))
    ):
        if target.startswith(_EXTERNAL):
            continue
        if target.startswith("#"):
            if target[1:] not in heading_slugs(md_path):
                broken.append(target)
            continue
        path_part, _, fragment = target.partition("#")
        resolved = (md_path.parent / path_part).resolve()
        if not resolved.exists():
            broken.append(target)
            continue
        if fragment and fragment not in heading_slugs(resolved):
            broken.append(target)
    return broken
