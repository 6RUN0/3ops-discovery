"""
Manifest 6.1 provenance labels vs every series/stream-producing file.

File-level presence only; the per-pipeline granularity for 030 lives in
test_database.py.

The checked set is derived by subtracting asymmetries.NOT_SERIES_PATHS
from the file glob rather than listed here. A hardcoded set can only be
wrong in the silent direction: a new domain file absent from it is not
reported as uncovered, it is simply never checked -- and provenance is
what keeps a spoofed job label distinguishable from a real one.
"""

from tests.static import alloy_config as ac
from tests.static import asymmetries


def _series_path_files() -> set[str]:
    every = {*ac.sources(), *ac.optional_sources()}
    return every - set(asymmetries.NOT_SERIES_PATHS)


def test_every_series_path_declares_host_and_collector() -> None:
    checked = _series_path_files()
    assert checked, "no series-producing files found"
    missing_host = checked - ac.files_with_host_provenance()
    assert not missing_host, f"no host provenance in: {missing_host}"
    missing_collector = checked - ac.files_with_collector_provenance()
    assert not missing_collector, (
        f"no collector provenance in: {missing_collector}"
    )


def test_no_phantom_exemptions() -> None:
    # The other direction, in the spirit of LABELS_UNREAD: an entry for a
    # file that no longer exists would quietly shrink the checked set the
    # day a file of that name comes back.
    every = {*ac.sources(), *ac.optional_sources()}
    phantom = set(asymmetries.NOT_SERIES_PATHS) - every
    assert not phantom, f"NOT_SERIES_PATHS names missing files: {phantom}"


def test_exempt_files_really_produce_nothing() -> None:
    # An exemption is a claim about the file, so it is checked, not
    # trusted: a file that attaches provenance is producing series and
    # does not belong in the table.
    labelled = ac.files_with_host_provenance() | (
        ac.files_with_collector_provenance()
    )
    wrong = set(asymmetries.NOT_SERIES_PATHS) & labelled
    assert not wrong, f"exempt files that do attach provenance: {wrong}"
