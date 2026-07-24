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
