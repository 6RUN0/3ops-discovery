"""
Manifest 6.2 allowlist vs labels promoted to Loki streams.

Covers the docker logs path (040/050), 060_otel resource attributes, and
080_host-logs static labels — no write path into loki.write bypasses the
cardinality discipline.
"""

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md


def test_all_paths_within_allowlist() -> None:
    promoted = (
        ac.promoted_stream_labels()
        | ac.otel_promoted_stream_labels()
        | ac.host_log_stream_labels()
    )
    allowlist = md.loki_label_allowlist()
    assert promoted <= allowlist, (
        f"labels outside manifest 6.2 allowlist: {promoted - allowlist}"
    )
