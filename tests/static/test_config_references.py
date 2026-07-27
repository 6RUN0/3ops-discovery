"""
Comments in the shipped config point at sections that exist.

The project keeps three surfaces in step by hand -- the manifest, the
config, and the comments inside the config -- and the gates covered only
the first pair. Commit 94d795a is what that costs: it corrected a
refuted claim in the manifest, in 040 and in the e2e compose, and left
the same claim standing in 020 and 030, where a reader of the reference
meets it first.

A comment cannot be checked for truth. Its citation can, and a citation
that no longer resolves is the cheap, mechanical half of the drift.
"""

import re

import pytest

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md

#: "manifest 8.4", "manifest section 9", "manifest sections 10.3.2, 10.3.4".
_REFERENCE = re.compile(
    r"manifest (?:sections?\s+)?"
    r"(\d+(?:\.\d+)*(?:\s*,\s*\d+(?:\.\d+)*)*)"
)
#: The design document the overlays used to cite. It is internal, it is
#: not shipped, and its numbering has nothing to do with the contract's.
_FOREIGN = re.compile(r"\bspec\s+\d+(?:\.\d+)*")
#: Anything that reads as a citation to a human. Deliberately looser than
#: _REFERENCE so a spelling the strict pattern misses is caught as drift
#: rather than silently going unchecked.
_LOOSE = re.compile(r"manifest\b[^\n]{0,20}?\d")


def _configs() -> dict[str, str]:
    return {**ac.sources(), **ac.optional_sources()}


def _cited(text: str) -> list[str]:
    return [
        number.strip()
        for match in _REFERENCE.finditer(text)
        for number in match.group(1).split(",")
    ]


@pytest.mark.parametrize("name", sorted(_configs()))
def test_every_cited_section_exists(name: str) -> None:
    known = md.section_numbers()
    missing = [n for n in _cited(_configs()[name]) if n not in known]
    assert not missing, (
        f"{name} cites manifest sections that do not exist: {missing}"
    )


@pytest.mark.parametrize("name", sorted(_configs()))
def test_no_config_cites_the_internal_design_document(name: str) -> None:
    # 070 and 080 shipped citing "spec 5.4" -- a section of a document
    # the reader of the archive never receives, numbered in a scheme that
    # is not the contract's. Every other file cites the manifest.
    foreign = _FOREIGN.findall(_configs()[name])
    assert not foreign, f"{name} cites a non-manifest source: {foreign}"


def test_the_scan_recognises_every_citation_a_reader_would() -> None:
    # The vacuity guard. Not "every file cites something" -- 010 and 090
    # legitimately cite nothing -- but "nothing that LOOKS like a citation
    # escapes the strict pattern". A comment reading "manifest sec. 8.4"
    # would otherwise be checked by no one while still reading as a
    # promise to the next maintainer.
    unparsed: dict[str, list[str]] = {}
    for name, text in _configs().items():
        strict = {m.start() for m in _REFERENCE.finditer(text)}
        missed = [
            text[m.start() : m.start() + 40]
            for m in _LOOSE.finditer(text)
            if m.start() not in strict
        ]
        if missed:
            unparsed[name] = missed
    assert not unparsed, f"citations the gate cannot check: {unparsed}"


def test_the_corpus_is_actually_cross_referenced() -> None:
    # And the other half: if the strict pattern ever stops matching
    # anything at all, both parametrised checks pass over empty lists.
    cited = [n for text in _configs().values() for n in _cited(text)]
    assert len(cited) > 10, f"suspiciously few manifest citations: {cited}"
