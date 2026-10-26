"""
Manifest 14 implementation registry vs the domain list of section 10.

The registry is what lets a deployment combine implementations per
domain; a domain name that is not in section 10 cannot be assigned to
anything, and a reference that skips a domain leaves it unimplemented.
"""

from tests.static import manifest_doc as md


def test_reference_implements_every_domain() -> None:
    assert md.implementations()["alloy"] == md.domains()


def test_registry_names_only_contract_domains() -> None:
    for name, domains in md.implementations().items():
        assert domains <= md.domains(), (
            f"{name}: unknown domains {domains - md.domains()}"
        )


def test_host_domains_are_listed_apart() -> None:
    assert md.host_domains() == {
        "host-metrics",
        "container-metrics",
        "host-logs",
    }
    assert md.host_domains() < md.domains()
