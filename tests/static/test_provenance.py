"""
Manifest 6.1 provenance labels vs every series/stream-producing file.

File-level presence only; the per-pipeline granularity for 030 lives in
test_database.py. 060_otel is deliberately absent: the OTLP path cannot
produce container/host provenance and the manifest 10.5 documents that
gap explicitly.
"""

from tests.static import alloy_config as ac

SERIES_PATH_FILES = {
    "020_metrics.alloy",
    "030_database.alloy",
    "035_blackbox.alloy",
    "037_snmp.alloy",
    "040_logs.alloy",
    "070_host-metrics.alloy",
    "075_container-metrics.alloy",
    "080_host-logs.alloy",
}


def test_every_series_path_declares_host_and_collector() -> None:
    missing_host = SERIES_PATH_FILES - ac.files_with_host_provenance()
    assert not missing_host, f"no host provenance in: {missing_host}"
    missing_collector = (
        SERIES_PATH_FILES - ac.files_with_collector_provenance()
    )
    assert not missing_collector, (
        f"no collector provenance in: {missing_collector}"
    )
