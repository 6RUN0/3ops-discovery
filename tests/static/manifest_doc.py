"""
Anchor-based extraction from docs/manifest.ru.md.

Every normative source is addressed by an anchor: the section number
plus a position inside it ("first code block", "first table", "first
code block after a marker line"). A missing anchor raises AnchorError
loudly, naming the section -- restructuring the manifest breaks the
gate explicitly instead of silently skipping a check. Deliberate
counterexamples (the forbidden profile in 8.1, the path traversal in
13.4, the fast-v1 illustration in 10.1.2) are never extracted because
no anchor addresses them.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "docs" / "manifest.ru.md"


class AnchorError(AssertionError):
    """A normative anchor was not found in the manifest."""


@cache
def _text() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def section(number: str) -> str:
    """Return the body of the section numbered ``number`` (e.g. "8.2")."""
    heading = re.search(rf"(?m)^(#+) {re.escape(number)}\. .*$", _text())
    if heading is None:
        raise AnchorError(f"manifest section {number} not found")
    level = len(heading.group(1))
    body = _text()[heading.end() :]
    # A section ends at the next heading of the same or higher level;
    # deeper subsections stay inside the body.
    stop = re.search(rf"(?m)^#{{2,{level}}} ", body)
    return body[: stop.start()] if stop else body


def _code_blocks(body: str) -> list[str]:
    return re.findall(r"(?ms)^```[\w-]*\n(.*?)^```$", body)


def code_block(
    number: str, index: int = 0, *, after: str | None = None
) -> str:
    """Fenced block #index of a section, optionally after a marker line."""
    body = section(number)
    if after is not None:
        pos = body.find(after)
        if pos < 0:
            raise AnchorError(
                f"marker {after!r} not found in manifest section {number}"
            )
        body = body[pos:]
    blocks = _code_blocks(body)
    if len(blocks) <= index:
        raise AnchorError(
            f"code block #{index} not found in manifest section {number}"
        )
    return blocks[index]


def table(number: str, index: int = 0) -> list[dict[str, str]]:
    """Pipe table #index of a section as a list of row dicts."""
    rows: list[list[str]] = []
    tables: list[list[list[str]]] = []
    for line in section(number).splitlines():
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif rows:
            tables.append(rows)
            rows = []
    if rows:
        tables.append(rows)
    if len(tables) <= index:
        raise AnchorError(
            f"table #{index} not found in manifest section {number}"
        )
    header, _separator, *body = tables[index]
    return [dict(zip(header, row, strict=True)) for row in body]


def _plain(cell: str) -> str:
    """Strip inline-code backticks and [text](link) markup from a cell."""
    cell = cell.strip("`")
    link = re.fullmatch(r"\[`?([^]`]+)`?\]\([^)]*\)", cell)
    return link.group(1) if link else cell


def scrape_profiles() -> dict[str, dict[str, str]]:
    """Section 8.2: profile name -> {interval, timeout}."""
    block = code_block("8.2", after="Базовые профили:")
    profiles: dict[str, dict[str, str]] = {}
    current = ""
    for line in block.splitlines():
        name = re.fullmatch(r"([a-z0-9-]+):", line.strip())
        pair = re.fullmatch(r"(interval|timeout): (\S+)", line.strip())
        if name and not line.startswith(" "):
            current = name.group(1)
            profiles[current] = {}
        elif pair and current:
            profiles[current][pair.group(1)] = pair.group(2)
    if not profiles:
        raise AnchorError("no scrape profiles parsed from section 8.2")
    return profiles


def log_profiles() -> set[str]:
    """Section 8.3: the base log profile names."""
    block = code_block("8.3", after="Базовые профили:")
    names = {
        line.strip()
        for line in block.splitlines()
        if line and not line.startswith(" ")
    }
    if not names:
        raise AnchorError("no log profiles parsed from section 8.3")
    return names


def db_profiles() -> set[str]:
    """Section 8.4: database profile names."""
    return set(code_block("8.4").split())


def db_types() -> set[str]:
    """Section 10.2: supported database types."""
    return set(code_block("10.2").split())


def db_default_ports() -> dict[str, str]:
    """Section 10.2 port table: database type -> default port."""
    return {_plain(row["Тип"]): _plain(row["Порт"]) for row in table("10.2")}


def secret_formats() -> dict[str, str]:
    """
    Section 9 per-type .dsn content-format table: type -> format.

    Only the keys are normative (the set of documented types); the format
    strings are illustrative and keep interior backticks/prose, since
    _plain strips only the outer backtick pair of a cell.
    """
    formats: dict[str, str] = {}
    for row in table("9"):
        fmt = _plain(row["Формат"])
        # Split BEFORE _plain: table() strips only the OUTER backtick pair
        # of a grouped cell like `mysql`, `mariadb`, leaving interior
        # backticks -- so _plain must run per token, not on the whole cell.
        for typ in row["Тип"].split(","):
            formats[_plain(typ.strip())] = fmt
    return formats


def optional_files() -> set[str]:
    """Section 14.5: names of the optional overlay files."""
    return {_plain(row["Файл"]) for row in table("14.5")}


def extension_points() -> set[str]:
    """Section 14.4: stable base exports overlays may reference."""
    return {_plain(row["Экспорт"]) for row in table("14.4")}


def secret_id_pattern() -> str:
    """Section 9: the secret-id validation regex."""
    return code_block("9", after="Допустимый шаблон:").strip()


def loki_label_allowlist() -> set[str]:
    """Section 6.2: labels allowed in Loki streams."""
    return set(code_block("6.2").split())


def env_defaults() -> dict[str, str]:
    """Section 14.1: RU_3OPS_DISCOVERY_* variable -> literal default."""
    return {
        _plain(row["Переменная"]): _plain(row["Default"])
        for row in table("14.1")
    }


def base_files() -> set[str]:
    """Section 14: file names of the base reference config."""
    return {_plain(row["Файл"]) for row in table("14")}


def alloy_image_tag() -> str:
    """Section 14: the pinned grafana/alloy image tag."""
    m = re.search(r"grafana/alloy:(v[0-9][\w.]*)", section("14"))
    if m is None:
        raise AnchorError("alloy image tag not found in section 14")
    return m.group(1)
