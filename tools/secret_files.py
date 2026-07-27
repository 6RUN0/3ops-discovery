"""
Writing a secret file the way manifest section 9 requires.

Section 9 asks that a secret file be readable by the Alloy user alone.
Everything else in this repository honoured that on the container side
and forgot it on the host side: the fixtures wrote credentials at
whatever the umask allowed (0644 in practice), and `nox -s demo` leaves
that directory behind in the working tree, not in a temp dir that goes
away with the run.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

#: Owner read/write, nothing for group or other.
SECRET_MODE = 0o600


def write_secret(path: Path, content: str, *, encoding: str = "ascii") -> Path:
    """Write ``content`` to ``path`` as an owner-only file; return the path."""
    # Created with the mode already set rather than chmod-ed afterwards:
    # a chmod leaves a window where the credential is on disk and
    # world-readable, and a crash inside that window leaves it there for
    # good. os.open applies the umask, so a wider umask cannot loosen
    # this -- but it cannot tighten a file that already exists either,
    # hence the explicit chmod for the overwrite case.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, SECRET_MODE)
    with os.fdopen(descriptor, "w", encoding=encoding) as handle:
        handle.write(content)
    os.chmod(path, SECRET_MODE)
    return path


def is_owner_only(path: Path) -> bool:
    """Return True if ``path`` grants nothing to group or other."""
    return not stat.S_IMODE(path.stat().st_mode) & 0o077
