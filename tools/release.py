"""
Build the release archive: the contract plus its reference config.

What ships is the pair, never one half of it. Configs alone do not tell
an operator which labels to put on a container, and the manifest alone
pins an Alloy image nobody can check against a config that is not there.

The archive is reproducible: tar carries no mtimes, uids or filesystem
order, so rebuilding the same tag yields the same sha256 and a published
checksum stays verifiable.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "docs" / "manifest.ru.md"

#: Files and directories the archive carries, repo-relative. Directories
#: ship whole; test_release.py pins the *.alloy set against COMBOS, so a
#: new overlay cannot quietly stay behind.
CONTENTS: tuple[str, ...] = (
    "LICENSE",
    "CHANGELOG.md",
    "CHANGELOG.ru.md",
    "docs/manifest.md",
    "docs/manifest.ru.md",
    "alloy",
    "alloy-optional",
)

#: Deployment instructions, renamed into the archive root: the
#: repository README is about gates and uv, which an operator unpacking
#: a config bundle has no use for.
ARCHIVE_README = "packaging/ARCHIVE-README.md"

#: A fixed timestamp for every member. Any constant works; this is the
#: Unix epoch, chosen so the value is obviously synthetic.
_EPOCH = 0
_VERSION = re.compile(r"(?m)^\*\*Версия спецификации:\*\* `(\d+\.\d+\.\d+)`")


class ReleaseError(RuntimeError):
    """The repository cannot produce a coherent release."""


def spec_version() -> str:
    """
    Return the contract version from the manifest header, e.g. "0.2.0".

    The single source of the number a release is named after: the
    virtual pyproject pins 0.0.0 on purpose, so nothing else in the
    repository is allowed to claim it knows the version.
    """
    found = _VERSION.search(MANIFEST.read_text(encoding="utf-8"))
    if found is None:
        raise ReleaseError(f"no spec version in the header of {MANIFEST}")
    return found.group(1)


def verify_tag(tag: str) -> str:
    """
    Check that a git tag names exactly the manifest version.

    The release workflow runs on a tag push, so this is what stops a
    ``v0.3.0`` tag from publishing an archive of the 0.2.0 contract.
    """
    version = spec_version()
    if tag != f"v{version}":
        raise ReleaseError(
            f"tag {tag} does not match the manifest: expected v{version}"
        )
    return version


def archive_name(version: str | None = None) -> str:
    """Return the release base name, without the .tar.gz suffix."""
    return f"3ops-discovery-{version or spec_version()}"


def tracked_files() -> tuple[str, ...]:
    """
    Return the repo-relative CONTENTS paths, as git tracks them.

    Enumerated by git rather than walked: a plain copy of a directory
    also picks up whatever untracked state happens to sit inside it,
    and the first build of this archive shipped an .omc/ session
    directory out of alloy/. What ships must equal what is versioned.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *CONTENTS],
        capture_output=True,
        check=True,
        cwd=REPO,
        text=True,
    ).stdout
    files = tuple(sorted(name for name in listed.split("\0") if name))
    missing = [
        entry
        for entry in CONTENTS
        if not any(
            name == entry or name.startswith(f"{entry}/") for name in files
        )
    ]
    if missing:
        raise ReleaseError(f"release content is untracked or gone: {missing}")
    return files


def stage(dest: Path, version: str | None = None) -> Path:
    """Lay the archive contents out under ``dest``/<name>, and return it."""
    root = dest / archive_name(version)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for relative in tracked_files():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / relative, target)
    readme = REPO / ARCHIVE_README
    if not readme.exists():
        raise ReleaseError(f"release content is missing: {ARCHIVE_README}")
    shutil.copy(readme, root / "README.md")
    return root


def _reset(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Strip the build machine out of a member's metadata."""
    info.mtime = _EPOCH
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    # Nothing shipped is executable, so umask must not leak in either.
    info.mode = 0o755 if info.isdir() else 0o644
    return info


def build(dist: Path, version: str | None = None) -> Path:
    """Stage, pack into dist/<name>.tar.gz and write SHA256SUMS."""
    version = version or spec_version()
    dist.mkdir(parents=True, exist_ok=True)
    root = stage(dist, version)
    archive = dist / f"{archive_name(version)}.tar.gz"
    # The gzip wrapper is opened by hand: tarfile.open("w:gz") stamps the
    # current time into the gzip header and hands no way to override it,
    # so every rebuild would differ despite identical contents.
    with (
        gzip.GzipFile(archive, "wb", compresslevel=9, mtime=_EPOCH) as gz,
        tarfile.open(fileobj=gz, mode="w") as tar,
    ):
        for path in sorted(root.rglob("*")):
            # recursive=False: rglob already yields every member, and
            # letting tar recurse too would add each one twice.
            tar.add(
                path,
                arcname=str(path.relative_to(dist)),
                recursive=False,
                filter=_reset,
            )
    shutil.rmtree(root)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / "SHA256SUMS").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    return archive
