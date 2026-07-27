"""
Manifest 6.1 series identity vs what the configuration stamps.

The identity of a series is the most consumer-visible thing this project
produces: a dashboard or an alert rule binds to `job` and `instance` and
breaks when either moves. It was written down for metrics and database
and left implicit for blackbox and snmp, where the values are literals
sitting in the config and nowhere else -- including `snmp_profile`,
which entered the contract as an anchor for a static gate.
"""

import pytest

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md

_DOMAINS = {"metrics", "database", "blackbox", "snmp"}


def test_identity_is_documented_for_every_domain_that_emits_series() -> None:
    assert set(md.series_identity()) == _DOMAINS


@pytest.mark.parametrize(
    ("domain", "file"),
    [("blackbox", "035_blackbox.alloy"), ("snmp", "037_snmp.alloy")],
)
def test_constant_job_matches_the_manifest(domain: str, file: str) -> None:
    # These two domains synthesise job from a literal rather than from a
    # label, so the literal IS the contract; nothing else records it.
    documented = md.series_identity()[domain]["`job`"]
    assert f"`{ac.constant_job(file)}`" in documented, (
        f"{file} stamps job={ac.constant_job(file)!r}, 6.1 says {documented!r}"
    )


def test_snmp_profile_label_is_part_of_the_contract() -> None:
    # It leaked into the data from a test -- the static gate reads the
    # profile name off this very label. Removing it is not an option
    # while dashboards may already group by it, so the honest move is to
    # document it and check that the two agree.
    documented = md.series_identity()["snmp"]["Дополнительно"]
    assert "snmp_profile" in documented
    (name,) = ac.snmp_scrape_pairs()
    assert name in md.snmp_scrape_profiles(), (
        f"{name} is not a manifest 8.5 snmp profile"
    )
