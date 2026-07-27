"""
The release archive stays bound to the contract it ships.

An artifact is one more place a version and a file set can be written
down, so it gets the same treatment as everything else here: the version
comes from the manifest and nowhere else, the shipped *.alloy set is the
one alloy_check validates, and a rebuild of the same tree is byte for
byte the same archive.
"""

import hashlib
import tarfile
from pathlib import Path

import pytest

from tests.static import manifest_doc as md
from tools import release
from tools.materialize import BASE_DIR, COMBOS, OPTIONAL_DIR


def _members(archive: Path) -> set[str]:
    with tarfile.open(archive, "r:gz") as tar:
        return {name.split("/", 1)[1] for name in tar.getnames()}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return release.build(tmp_path_factory.mktemp("dist"))


def test_version_comes_from_the_manifest_header() -> None:
    # pyproject pins 0.0.0 on purpose (virtual project), so the manifest
    # header is the only place allowed to state the contract version.
    version = release.spec_version()
    header = md.MANIFEST.read_text(encoding="utf-8").partition("## 1.")[0]
    assert f"`{version}`" in header
    assert release.archive_name().endswith(version)
    assert version != "0.0.0", "the pyproject placeholder leaked in"


def test_tag_must_match_the_manifest_version() -> None:
    version = release.spec_version()
    assert release.verify_tag(f"v{version}") == version
    with pytest.raises(release.ReleaseError, match="does not match"):
        release.verify_tag("v999.0.0")
    with pytest.raises(release.ReleaseError, match="does not match"):
        release.verify_tag(version)  # missing the v prefix


def test_archive_ships_every_validated_alloy_file(built: Path) -> None:
    # The set alloy_check validates: base plus every overlay named by a
    # combo. An overlay added to the repo but forgotten here would ship
    # a config nobody validated -- or not ship at all.
    validated = {f"alloy/{path.name}" for path in BASE_DIR.glob("*.alloy")}
    validated |= {
        f"alloy-optional/{name}" for names in COMBOS.values() for name in names
    }
    shipped = {name for name in _members(built) if name.endswith(".alloy")}
    assert shipped == validated


def test_every_optional_file_is_named_by_a_combo() -> None:
    # Guards the other direction of the check above: an overlay that no
    # combo mentions would satisfy it while never being validated.
    on_disk = {path.name for path in OPTIONAL_DIR.glob("*.alloy")}
    in_combos = {name for names in COMBOS.values() for name in names}
    assert on_disk == in_combos


def test_archive_carries_the_contract_and_the_deployment_readme(
    built: Path,
) -> None:
    members = _members(built)
    assert {"docs/manifest.ru.md", "docs/manifest.md", "LICENSE"} <= members
    assert "README.md" in members
    with tarfile.open(built, "r:gz") as tar:
        entry = tar.extractfile(f"{release.archive_name()}/README.md")
        assert entry is not None
        readme = entry.read().decode("utf-8")
    # The deployment readme, not the repository one: an operator gets
    # instructions for running Alloy, not for running the gates.
    assert "uv run nox" not in readme
    assert "alloy run --stability.level=experimental" in readme


def test_archive_carries_nothing_else(built: Path) -> None:
    # The first build of this archive copied whole directories and swept
    # an untracked .omc/ session directory into alloy/. Nothing outside
    # the declared contents may ship, secrets and scratch state least of
    # all.
    allowed_roots = {"alloy", "alloy-optional", "docs"}
    for name in _members(built):
        head, _, tail = name.partition("/")
        if tail:
            assert head in allowed_roots, f"unexpected directory: {name}"
        assert not name.startswith("."), f"dotfile shipped: {name}"
        assert not name.endswith((".dsn", ".redispass", ".snmp", ".ipmi")), (
            f"secret-shaped file shipped: {name}"
        )


def test_rebuild_is_byte_for_byte_identical(tmp_path: Path) -> None:
    # A published checksum is only useful if the archive can be rebuilt
    # from the tag and compared; mtimes and uids would break that.
    first = release.build(tmp_path / "one")
    second = release.build(tmp_path / "two")
    assert hashlib.sha256(first.read_bytes()).hexdigest() == (
        hashlib.sha256(second.read_bytes()).hexdigest()
    )


def test_checksum_file_matches_the_archive(built: Path) -> None:
    line = (built.parent / "SHA256SUMS").read_text(encoding="utf-8").strip()
    digest, name = line.split("  ")
    assert name == built.name
    assert digest == hashlib.sha256(built.read_bytes()).hexdigest()
