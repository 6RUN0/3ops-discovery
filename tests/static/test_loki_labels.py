"""
Manifest 6.2 allowlist vs labels promoted to Loki streams.

Phase 1 checks the docker logs path (040). Phase 2 extends the scanner
to 060_otel (resource attributes) and phase 3 to 080_host-logs, so that
no path bypasses the cardinality discipline.
"""

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md


def test_docker_path_labels_within_allowlist() -> None:
    promoted = ac.promoted_stream_labels()
    allowlist = md.loki_label_allowlist()
    assert promoted <= allowlist, (
        f"labels outside manifest 6.2 allowlist: {promoted - allowlist}"
    )
