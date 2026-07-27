"""tools.materialize: overlay composition and collision guard."""

from pathlib import Path

import pytest

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
