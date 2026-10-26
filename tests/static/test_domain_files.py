"""
tools.materialize.DOMAIN_FILES: the reference composed by domain.

Every *.alloy file must belong to a domain, every domain of the section 14
registry must have a file set, and the manifest file tables (14.4, 14.4.3)
must name the same domains per file, so a deployment that takes "only
logs" gets a set alloy_check validated on its own.
"""

import re

import pytest
from noxfile import alloy_validate_args

from tests.static import manifest_doc as md
from tools import materialize as mz


def test_domains_equal_reference_registry() -> None:
    assert set(mz.DOMAIN_FILES) == md.implementations()["alloy"]


def test_every_file_on_disk_belongs_to_a_domain() -> None:
    # A file outside every domain would silently reach no domain deploy.
    on_disk = {
        p.name
        for d in (mz.BASE_DIR, mz.OPTIONAL_DIR)
        for p in d.glob("*.alloy")
    }
    assert set().union(*mz.DOMAIN_FILES.values()) == on_disk


def test_default_domains_are_exactly_base() -> None:
    assert set(mz.files_for(mz.DEFAULT_DOMAINS)) == {
        p.name for p in mz.BASE_DIR.glob("*.alloy")
    }


def test_experimental_files_are_the_foreach_files() -> None:
    # The experimental flag is passed only for sets containing these
    # files; an experimental block elsewhere would be masked by it.
    with_foreach = {
        p.name
        for d in (mz.BASE_DIR, mz.OPTIONAL_DIR)
        for p in d.glob("*.alloy")
        if re.search(r'^foreach\s+"', p.read_text(), re.M)
    }
    assert with_foreach == set(mz.EXPERIMENTAL_FILES)


def test_only_database_needs_experimental() -> None:
    assert mz.needs_experimental(["database"])
    assert not any(
        mz.needs_experimental([d]) for d in mz.DOMAIN_FILES if d != "database"
    )


def test_unknown_domain_is_named() -> None:
    with pytest.raises(ValueError, match="'log'"):
        mz.files_for(["log"])


def test_manifest_file_tables_match_domain_files() -> None:
    expected: dict[str, set[str]] = {}
    for domain, files in mz.DOMAIN_FILES.items():
        for name in files:
            expected.setdefault(name, set()).add(domain)
    assert md.reference_file_domains() == expected


def test_every_domain_has_its_own_combo() -> None:
    for domain in mz.DOMAIN_FILES:
        assert mz.COMBOS[f"domain-{domain}"] == (domain,)


def test_alloy_check_passes_the_experimental_flag_only_with_database() -> None:
    # alloy_check builds its validate command from this function; a combo
    # without database must validate at the default stability level, so
    # the flag cannot mask an experimental block outside 030.
    flag = "--stability.level=experimental"
    with_flag = {"base", "all", "all-snmp", "domain-database"}
    for combo, domains in mz.COMBOS.items():
        args = alloy_validate_args(domains)
        assert args[0] == "validate"
        assert args[-1] == "/etc/alloy"
        assert (flag in args) is (combo in with_flag), combo
