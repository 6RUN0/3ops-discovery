"""
Anchor-based extraction from docs/manifest.ru.md.

Every normative source is addressed by an anchor: the section number
plus a position inside it ("first code block", "first table", "first
code block after a marker line"). A missing anchor raises AnchorError
loudly, naming the section -- restructuring the manifest breaks the
gate explicitly instead of silently skipping a check. Deliberate
counterexamples (the forbidden profile in 8.1, the path traversal in
13.4) are never extracted because no anchor addresses them.
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


def section(number: str, *, subsections: bool = True) -> str:
    """
    Return the body of the section numbered ``number`` (e.g. "8.2").

    With ``subsections=False`` the body stops at the first heading of any
    deeper level, so a positional anchor addresses THIS section's own
    tables and blocks and cannot be redirected by a table added to a
    subsection below it.
    """
    heading = re.search(rf"(?m)^(#+) {re.escape(number)}\. .*$", _text())
    if heading is None:
        raise AnchorError(f"manifest section {number} not found")
    level = len(heading.group(1))
    body = _text()[heading.end() :]
    if not subsections:
        # Any heading at all ends the section's own body.
        stop = re.search(r"(?m)^#+ ", body)
        return body[: stop.start()] if stop else body
    # A section ends at the next heading of the same or higher level;
    # deeper subsections stay inside the body. Level 1 has nothing above
    # it, so the "{2,level}" quantifier would be invalid rather than
    # merely unmatched -- guard it instead of raising re.error.
    if level < 2:
        raise AnchorError(f"section {number} is a document title, not a body")
    stop = re.search(rf"(?m)^#{{2,{level}}} ", body)
    return body[: stop.start()] if stop else body


@cache
def section_numbers() -> frozenset[str]:
    """Every section number that carries a heading, e.g. {"9", "10.6.1"}."""
    numbers = frozenset(re.findall(r"(?m)^#+ (\d+(?:\.\d+)*)\. ", _text()))
    if not numbers:
        raise AnchorError("no numbered headings found in the manifest")
    return numbers


def _code_blocks(body: str) -> list[str]:
    return re.findall(r"(?ms)^```[\w-]*\n(.*?)^```$", body)


def code_block(
    number: str, index: int = 0, *, after: str | None = None
) -> str:
    """Fenced block #index of a section's own body, after a marker line."""
    body = section(number, subsections=False)
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


def yaml_blocks(number: str) -> list[str]:
    """Every ```yaml fenced block of a section, in document order."""
    blocks = re.findall(r"(?ms)^```yaml\n(.*?)^```$", section(number))
    if not blocks:
        raise AnchorError(f"no yaml block found in manifest section {number}")
    return blocks


def table(
    number: str, index: int = 0, *, after: str | None = None
) -> list[dict[str, str]]:
    """
    Pipe table #index of a section's OWN body, as a list of row dicts.

    Own body, not the whole subtree: a positional anchor over the subtree
    silently follows a table inserted into a subsection above the
    intended one, and a one-sided check survives that quietly. ``after``
    names the table by a preceding marker line where position alone is
    too weak an address.
    """
    body = section(number, subsections=False)
    if after is not None:
        pos = body.find(after)
        if pos < 0:
            raise AnchorError(
                f"marker {after!r} not found in manifest section {number}"
            )
        body = body[pos:]
    rows: list[list[str]] = []
    tables: list[list[list[str]]] = []
    for line in body.splitlines():
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
    header, _separator, *data_rows = tables[index]
    return [dict(zip(header, row, strict=True)) for row in data_rows]


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


def snmp_scrape_profiles() -> dict[str, dict[str, str]]:
    """Section 8.5: snmp profile name -> {interval, timeout}."""
    block = code_block("8.5", after="SNMP-профили:")
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
        raise AnchorError("no snmp scrape profiles parsed from section 8.5")
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


def log_profile_fields() -> dict[str, set[str]]:
    """Return the section 8.3 table: log profile -> structured metadata."""
    fields = {
        _plain(row["Профиль"]): set(
            re.findall(r"`(\w+)`", row["Поля в structured metadata"])
        )
        for row in table("8.3")
    }
    if not fields:
        raise AnchorError("no log profile fields parsed from section 8.3")
    return fields


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


def snmp_auth_versions() -> set[int]:
    """Section 10.6.1: the numeric `version` values the contract allows."""
    m = re.search(r"`version ∈ \{([^}]+)\}`", section("10.6.1"))
    if m is None:
        raise AnchorError("snmp auth version allowlist not found in 10.6.1")
    parts = [part.strip() for part in m.group(1).split(",")]
    if not all(part.isdigit() for part in parts):
        # The field is numeric; a `{v2c, v3}` spelling is the drift this
        # anchor exists to catch, so fail as a missing anchor, not ValueError.
        raise AnchorError(
            f"snmp auth version allowlist is not numeric: {m.group(1)!r}"
        )
    return {int(part) for part in parts}


def snmp_auth_level_fields() -> dict[str, set[str]]:
    """Section 10.6.1: v3 security_level -> fields it makes mandatory."""
    block = code_block("10.6.1", after="**Обязательные поля v3 по")
    fields: dict[str, set[str]] = {}
    for line in block.splitlines():
        level, separator, values = line.partition(":")
        if separator:
            fields[level.strip()] = {
                value.strip() for value in values.split("|") if value.strip()
            }
    if not fields:
        raise AnchorError("no snmp auth level fields parsed from 10.6.1")
    return fields


def snmp_auth_enums() -> dict[str, set[str]]:
    """Section 10.6.1: v3 field -> allowed values."""
    block = code_block("10.6.1", after="**Enum-ы полей v3:**")
    enums: dict[str, set[str]] = {}
    for line in block.splitlines():
        field, _, values = line.partition(":")
        if values.strip():
            enums[field.strip()] = {v.strip() for v in values.split("|")}
    if not enums:
        raise AnchorError("no snmp auth enums parsed from section 10.6.1")
    return enums


def domain_labels(number: str) -> dict[str, bool]:
    """Parse a 10.x labels table into label name -> mandatory flag."""
    labels = {
        _plain(row["Label"]): _plain(row["Обязательный"]) == "Да"
        for row in table(number)
    }
    if not labels:
        raise AnchorError(f"no labels parsed from section {number}")
    return labels


def series_identity() -> dict[str, dict[str, str]]:
    """Return the section 6.1 identity table: domain -> its row."""
    rows = {
        _plain(row["Домен"]): row
        for row in table("6.1")
        if "Домен" in row and "`job`" in row
    }
    if not rows:
        raise AnchorError("series identity table not found in section 6.1")
    return rows


def default_profile(number: str, label: str) -> str:
    """Return the default profile a 10.x labels table names for ``label``."""
    for row in table(number):
        if _plain(row["Label"]) == label:
            found = re.search(r"по умолчанию `([\w-]+)`", row["Значение"])
            if found is None:
                raise AnchorError(
                    f"section {number} names no default for {label}"
                )
            return found.group(1)
    raise AnchorError(f"label {label} not found in manifest section {number}")


def domain_label_values(number: str, label: str) -> set[str]:
    """
    Return the backticked values a 10.x labels table allows for a label.

    Only literal values are returned: a descriptive cell ("Порт metrics
    endpoint") yields the empty set, so a caller comparing against a
    config allowlist must decide what an empty answer means rather than
    silently agreeing with it.
    """
    for row in table(number):
        if _plain(row["Label"]) == label:
            return set(re.findall(r"`([^`]+)`", row["Значение"]))
    raise AnchorError(f"label {label} not found in manifest section {number}")


@cache
def labels_sections() -> tuple[str, ...]:
    """
    Return every 10.x subsection titled "Labels", in document order.

    Derived from the manifest rather than listed in the gate: a domain
    added with its labels subsection is covered the moment it is written
    down, and a hand-kept list would have to be remembered exactly when
    attention is on the new domain instead. That is how 10.7.1 stayed
    outside the coverage gate.
    """
    found = tuple(re.findall(r"(?m)^#+ (10(?:\.\d+)*)\. Labels$", _text()))
    if not found:
        raise AnchorError("no 10.x Labels subsections found in the manifest")
    return found


def domain_label_names(number: str) -> set[str]:
    """
    Return the contract label names documented in a 10.x Labels subsection.

    Two shapes are accepted. Most domains use a pipe table carrying a
    mandatory column; the declarative ipmi domain (10.7.1) lists bare
    names in a text block, because nothing reads those labels and the
    contract has never said which of them a container must declare.
    Converting it to a table would mean inventing that column, so the
    extractor bends instead of the specification.
    """
    try:
        names = set(domain_labels(number))
    except AnchorError:
        names = {
            line.strip()
            for line in code_block(number).splitlines()
            if line.strip()
        }
    stray = {name for name in names if not name.startswith("ru.3ops.")}
    if stray or not names:
        raise AnchorError(
            f"section {number} does not read as a labels list: "
            f"{sorted(stray) or 'empty'}"
        )
    return names


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


def provenance_labels() -> set[str]:
    """Section 6.1: label names Alloy must attach when available."""
    names = {
        line.split("=")[0].strip()
        for line in code_block("6.1").splitlines()
        if line.strip()
    }
    if not names:
        raise AnchorError("no provenance labels parsed from section 6.1")
    return names


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
