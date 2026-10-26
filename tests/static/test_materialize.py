"""tools.materialize: domain composition, stale-file cleanup, collisions."""

import re
from pathlib import Path

import pytest

from tests.static import alloy_config as ac
from tools import materialize as mz


def _alloy_names(dest: Path) -> set[str]:
    return {p.name for p in dest.glob("*.alloy")}


def _on_disk() -> set[str]:
    return {
        p.name
        for d in (mz.BASE_DIR, mz.OPTIONAL_DIR)
        for p in d.glob("*.alloy")
    }


def test_materialize_is_idempotent_on_a_reused_dest(tmp_path: Path) -> None:
    # alloy_check materializes into nox's persistent tmp, so the same dest
    # is reused across runs; re-materializing must overwrite, not raise.
    dest = tmp_path / "cfg"
    mz.materialize(dest, ["otel"])
    mz.materialize(dest, ["otel"])
    assert _alloy_names(dest) == set(mz.files_for(["otel"]))
    assert "090_output-metrics.alloy" in _alloy_names(dest)


def test_materialize_rejects_a_name_present_in_both_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Copying from "whichever directory has it" would pick one of two
    # different files silently; failing names the offending file.
    base, optional = tmp_path / "base", tmp_path / "optional"
    for directory in (base, optional):
        directory.mkdir()
        (directory / "010_dup.alloy").write_text("", encoding="utf-8")
    monkeypatch.setattr(mz, "BASE_DIR", base)
    monkeypatch.setattr(mz, "OPTIONAL_DIR", optional)
    monkeypatch.setattr(mz, "DOMAIN_FILES", {"dup": ("010_dup.alloy",)})
    with pytest.raises(FileExistsError, match=r"010_dup\.alloy"):
        mz.materialize(tmp_path / "cfg", ["dup"])


def test_materialize_removes_stale_files_from_a_reused_dest(
    tmp_path: Path,
) -> None:
    # A file deleted from the repo must not survive in a reused dest:
    # alloy_check would keep validating a graph that no longer exists
    # (renames fail loudly on duplicate names, deletions passed silently).
    dest = tmp_path / "cfg"
    mz.materialize(dest, ["otel"])
    mz.materialize(dest, ["metrics"])
    assert not (dest / "060_otel.alloy").exists()


def test_full_set_then_one_domain_leaves_only_that_domain(
    tmp_path: Path,
) -> None:
    # A reused dest after the full set must hold exactly the logs files:
    # a leftover 030 or 060 would make "logs alone" validate a graph no
    # logs-only deploy has.
    dest = tmp_path / "cfg"
    mz.materialize(dest, mz.COMBOS["all-snmp"])
    mz.materialize(dest, ["logs"])
    assert _alloy_names(dest) == set(mz.files_for(["logs"]))


def test_unknown_domain_leaves_a_reused_dest_untouched(
    tmp_path: Path,
) -> None:
    # The domain check runs before cleanup: a typo must not wipe or
    # half-rewrite the directory a previous run left behind.
    dest = tmp_path / "cfg"
    mz.materialize(dest, ["otel"])
    before = {p.name: p.read_bytes() for p in dest.iterdir()}
    with pytest.raises(ValueError, match="'log'"):
        mz.materialize(dest, ["logs", "log"])
    assert {p.name: p.read_bytes() for p in dest.iterdir()} == before


def test_files_for_is_a_sorted_union() -> None:
    files = mz.files_for(["logs", "metrics"])
    assert files == tuple(sorted(files))
    assert set(files) == set(mz.DOMAIN_FILES["logs"]) | set(
        mz.DOMAIN_FILES["metrics"]
    )


def test_named_combos_select_the_documented_domains() -> None:
    assert mz.COMBOS["base"] == mz.DEFAULT_DOMAINS
    assert set(mz.COMBOS["all-snmp"]) == set(mz.DOMAIN_FILES)
    assert set(mz.COMBOS["all"]) == set(mz.DOMAIN_FILES) - {"snmp"}


def test_one_combo_contains_every_file_together() -> None:
    # Pairwise interactions (name collisions, doubled series) surface
    # only in a combo carrying ALL files at once; per-domain combos would
    # not miss a file's removal from it.
    assert any(
        set(mz.files_for(domains)) == _on_disk()
        for domains in mz.COMBOS.values()
    )


def test_every_file_provider_overlay_declares_its_side_cars() -> None:
    # The completeness half of PROVIDER_FILES. A top-level local.file is
    # resolved when the graph is built, so an overlay that grows one and
    # is not listed here fails `validate` with a missing path -- but only
    # in the combination that selects it, and only once someone runs the
    # Docker gate. Derived from the config so the table cannot lag.
    needing: set[str] = set()
    for name, text in ac.optional_sources().items():
        if re.search(r'(?m)^local\.file "', text):
            needing.add(name)
    assert set(mz.PROVIDER_FILES) == needing, (
        "PROVIDER_FILES disagrees with the overlays that declare a "
        "top-level local.file"
    )


def test_provider_files_are_collected_per_combination() -> None:
    assert mz.provider_files(()) == ()
    assert mz.provider_files(("060_otel.alloy",)) == ()
    snmp = mz.provider_files(mz.files_for(["snmp"]))
    assert set(snmp) == {"snmp_targets.yaml", "snmp_auths.yaml"}
    # Every combination that selects the snmp domain gets them, which is
    # what the alloy_check session branches on.
    for combo, domains in mz.COMBOS.items():
        expected = "snmp" in domains
        files = mz.files_for(domains)
        assert bool(mz.provider_files(files)) is expected, (
            f"combo {combo} disagrees about needing provider files"
        )


def test_materialize_clears_stale_provider_files(tmp_path: Path) -> None:
    # A reused directory that keeps a device file from a previous run
    # would let a combination WITHOUT the snmp domain validate against
    # files it does not declare -- the same class as a stale *.alloy.
    dest = tmp_path / "cfg"
    mz.materialize(dest, ["snmp"])
    (dest / "snmp_targets.yaml").write_text("[]", encoding="utf-8")
    (dest / "snmp_auths.yaml").write_text("auths: {}", encoding="utf-8")
    mz.materialize(dest, ["metrics"])
    assert not (dest / "snmp_targets.yaml").exists()
    assert not (dest / "snmp_auths.yaml").exists()
    assert not (dest / "037_snmp.alloy").exists()


def test_materialize_creates_missing_parent_directories(
    tmp_path: Path,
) -> None:
    # nox hands a dest under a tmp tree that may not exist yet; a
    # non-recursive mkdir would fail on the first missing parent.
    dest = tmp_path / "missing" / "parent" / "cfg"
    mz.materialize(dest, ["logs"])
    assert _alloy_names(dest) == set(mz.files_for(["logs"]))


def test_unknown_file_name_error_names_both_directories() -> None:
    # The message is the only pointer to where a DOMAIN_FILES entry was
    # looked up, so it must survive as text, not as an empty exception.
    with pytest.raises(FileNotFoundError, match=r"neither .* nor "):
        mz._source("999_absent.alloy")
