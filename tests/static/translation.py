"""
Structural skeletons of the translated documents.

Every other static gate reads its normative facts from the Russian
originals alone, so a translation is unbound by construction: nothing
makes it follow a change to the contract, and a stale English manifest
would read exactly like a fresh one. Prose cannot be compared, but the
SKELETON can -- heading levels, section numbers, code fence languages,
table rows and list items. A section added, dropped or renumbered on one
side surfaces here instead of silently shipping a lie to the reader.
"""

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Translated documents, Russian original first. The manifest pair is the
#: load-bearing one: docs/manifest.ru.md is the contract and its English
#: twin is explicitly non-normative, so this gate is the only thing
#: holding the two together.
PAIRS: tuple[tuple[str, str], ...] = (
    ("docs/manifest.ru.md", "docs/manifest.md"),
    ("README.ru.md", "README.md"),
    ("CHANGELOG.ru.md", "CHANGELOG.md"),
)

_FENCE = re.compile(r"(?ms)^```.*?^```$")
_FENCE_MARKER = re.compile(r"(?m)^```(\S*)")
_HEADING = re.compile(r"(?m)^(#{1,6}) (.+)$")
_SECTION_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\.")


@dataclass(frozen=True)
class Skeleton:
    """Language-independent structure of a markdown document."""

    heading_levels: tuple[int, ...]
    section_numbers: tuple[str, ...]
    fence_languages: tuple[str, ...]
    table_rows: int
    list_items: int


def skeleton(md_path: Path) -> Skeleton:
    """Structure of a markdown file, with all prose stripped out."""
    text = md_path.read_text(encoding="utf-8")
    # Every second marker closes a block and carries no info string.
    fences = tuple(_FENCE_MARKER.findall(text)[::2])
    prose = _FENCE.sub("", text)
    headings = _HEADING.findall(prose)
    numbers = tuple(
        match.group(1)
        for _, title in headings
        if (match := _SECTION_NUMBER.match(title))
    )
    lines = prose.splitlines()
    return Skeleton(
        heading_levels=tuple(len(hashes) for hashes, _ in headings),
        section_numbers=numbers,
        fence_languages=fences,
        table_rows=sum(1 for line in lines if line.startswith("|")),
        list_items=sum(1 for line in lines if line.startswith("- ")),
    )
