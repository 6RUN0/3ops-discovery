"""tools.materialize: overlay composition and collision guard."""

import re
from pathlib import Path

import pytest

from tests.static import alloy_config as ac
from tools import materialize as mz


def test_materialize_is_idempotent_on_a_reused_dest(tmp_path: Path) -> None:
    # alloy_check materializes into nox's persistent tmp, so the same dest
    # is reused across runs; re-materializing must overwrite, not raise.
    dest = tmp_path / "cfg"
    mz.materialize(dest, optional=["060_otel.alloy"])
    mz.materialize(dest, optional=["060_otel.alloy"])
    names = {p.name for p in dest.glob("*.alloy")}
    assert "060_otel.alloy" in names
    assert "090_outputs.alloy" in names  # a base file came along too


def test_materialize_rejects_an_optional_shadowing_a_base_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileExistsError, match="collides with a base file"):
        mz.materialize(tmp_path / "cfg", optional=["090_outputs.alloy"])


def test_materialize_removes_stale_files_from_a_reused_dest(
    tmp_path: Path,
) -> None:
    # A file deleted from the repo must not survive in a reused dest:
    # alloy_check would keep validating a graph that no longer exists
    # (renames fail loudly on duplicate names, deletions passed silently).
    dest = tmp_path / "cfg"
    mz.materialize(dest, optional=["060_otel.alloy"])
    mz.materialize(dest, optional=[])
    assert not (dest / "060_otel.alloy").exists()


def test_one_combo_contains_every_overlay_together() -> None:
    # Pairwise overlay interactions (name collisions, doubled series)
    # surface only in a combo carrying ALL overlays at once; coverage of
    # each file alone (the test below) would not miss its removal.
    on_disk = {p.name for p in mz.OPTIONAL_DIR.glob("*.alloy")}
    assert any(set(files) == on_disk for files in mz.COMBOS.values())


def test_combos_cover_every_overlay_on_disk() -> None:
    # Nothing else ties COMBOS to the directory: an overlay could sit
    # on disk (and in manifest 14.5) yet never reach alloy_check.
    covered = set().union(*mz.COMBOS.values())
    on_disk = {p.name for p in mz.OPTIONAL_DIR.glob("*.alloy")}
    assert covered == on_disk


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
    snmp = mz.provider_files(("037_snmp.alloy",))
    assert set(snmp) == {"snmp_targets.yaml", "snmp_auths.yaml"}
    # And every combination that selects the overlay gets them, which is
    # what the alloy_check session now branches on instead of matching a
    # file name it happens to know.
    for combo, optional in mz.COMBOS.items():
        expected = "037_snmp.alloy" in optional
        assert bool(mz.provider_files(optional)) is expected, (
            f"combo {combo} disagrees about needing provider files"
        )


def test_materialize_clears_stale_provider_files(tmp_path: Path) -> None:
    # A reused directory that keeps a device file from a previous run
    # would let a combination WITHOUT the snmp overlay validate against
    # files it does not declare -- the same class as the stale *.alloy
    # the glob already handled.
    dest = tmp_path / "cfg"
    mz.materialize(dest, ("037_snmp.alloy",))
    (dest / "snmp_targets.yaml").write_text("[]", encoding="utf-8")
    (dest / "snmp_auths.yaml").write_text("auths: {}", encoding="utf-8")
    mz.materialize(dest, ())
    assert not (dest / "snmp_targets.yaml").exists()
    assert not (dest / "snmp_auths.yaml").exists()
    assert not (dest / "037_snmp.alloy").exists()
