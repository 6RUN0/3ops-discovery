"""
Manifest 14 implementation registry vs the domain list of section 10.

The registry is what lets a deployment combine implementations per
domain; a domain name that is not in section 10 cannot be assigned to
anything, and a reference that skips a domain leaves it unimplemented.
"""

import pytest

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


def test_an_empty_registry_is_an_anchor_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(md, "table", lambda _section: [])
    with pytest.raises(md.AnchorError) as caught:
        md.implementations()
    assert str(caught.value) == "no implementations parsed from section 14"
