"""Markdown link extraction and GitHub-style anchor resolution.

Backs test_doc_links: collects the repo's markdown files, computes the
heading slugs GitHub generates for them, and resolves every relative
link (path and optional #fragment) against the tree.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_EXTERNAL = ("http://", "https://", "mailto:")
_FENCE = re.compile(r"(?ms)^```.*?^```$")
_HEADING = re.compile(r"(?m)^#{1,6} (.+)$")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


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


def heading_slugs(md_path: Path) -> set[str]:
    """All heading anchors of a markdown file."""
    seen: dict[str, int] = {}
    prose = _prose(md_path.read_text(encoding="utf-8"))
    return {slugify(h, seen) for h in _HEADING.findall(prose)}


def broken_links(md_path: Path) -> list[str]:
    """Relative link targets that do not resolve (path or fragment)."""
    broken: list[str] = []
    prose = _prose(md_path.read_text(encoding="utf-8"))
    for target in _LINK.findall(prose):
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
