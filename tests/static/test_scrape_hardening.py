"""
Properties every prometheus.scrape must carry, wherever it lives.

The scrape profile gates pair a filter with its scrape and check the
cadence of the pair. These are the orthogonal checks: invariants that
hold for EVERY scrape in the reference, including the ones no profile
addresses (database, the host and container overlays). That distinction
is the point -- a copied profile pair inherits its neighbour's
properties, a brand new domain inherits nothing.
"""

import re

import pytest

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md


def _declared() -> int:
    """Count `prometheus.scrape "…" {` headers by a naive text scan."""
    every = {**ac.sources(), **ac.optional_sources()}
    return sum(
        len(re.findall(r'prometheus\.scrape "\w+" \{', text))
        for text in every.values()
    )


def test_the_scan_finds_every_declared_scrape() -> None:
    # The completeness half of the gates below: they can only be as good
    # as the extractor, and the database blocks sit indented inside a
    # foreach where a line-anchored regex sees nothing. Without this,
    # a parser regression would turn every assertion into a vacuous
    # pass over an empty list.
    assert len(ac.scrape_blocks()) == _declared()
    assert _declared() > 0


@pytest.mark.parametrize(
    ("file", "label", "body"),
    [(f, label, body) for f, label, body in ac.scrape_blocks()],
    ids=[f"{f}:{label}" for f, label, _ in ac.scrape_blocks()],
)
def test_scrape_does_not_follow_redirects(
    file: str, label: str, body: str
) -> None:
    # prometheus.scrape follows redirects by default, so a scraped
    # container can answer 302 and point the collector at an address no
    # label is allowed to name. The manifest 13.5 promise that SSRF is
    # excluded for metrics and database holds for the first request only
    # unless this is off.
    assert re.search(r"follow_redirects\s*=\s*false", body), (
        f"{file}: scrape {label} may follow a redirect out of the target"
    )


@pytest.mark.parametrize(
    ("file", "label", "body"),
    [(f, label, body) for f, label, body in ac.scrape_blocks()],
    ids=[f"{f}:{label}" for f, label, _ in ac.scrape_blocks()],
)
def test_scrape_states_its_own_cadence(
    file: str, label: str, body: str
) -> None:
    # The four database blocks set neither, so the cadence of a whole
    # contract domain was whatever prometheus.scrape defaults to -- an
    # upstream release could have moved it without a line changing here.
    # A value a consumer observes belongs to us, not to the version of
    # Alloy that happens to be installed.
    for argument in ("scrape_interval", "scrape_timeout"):
        assert re.search(rf'{argument}\s*=\s*"\S+"', body), (
            f"{file}: scrape {label} inherits {argument} from Alloy"
        )


def test_manifest_states_why_ssrf_is_excluded() -> None:
    # Binding the text to the config: the guarantee and the setting that
    # earns it must be written down together, or the next reader takes
    # the address construction alone for the whole reason.
    trust = md.section("13.5")
    assert "follow_redirects = false" in trust
