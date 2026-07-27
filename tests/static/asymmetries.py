"""
Allowed "manifest is wider than the config" asymmetries.

One explicit data structure instead of exceptions scattered through
check code: every deliberate gap is listed with its reason, so widening
the table is a visible diff-level decision. Entries marked "phase 2"
leave the table when those pipelines land in phase 2.

The subset invariant is a property of the REFERENCE config; user
overlay names (manifest customization section) are legal by pattern
and are not checked by these gates.
"""

#: Documented discovery labels the reference config deliberately never
#: reads. test_labels_coverage.py enforces both directions: an
#: undocumented unread label fails the gate, and so does a stale entry
#: here once the config starts reading the label.
LABELS_UNREAD: dict[str, str] = {
    "ru.3ops.discovery.database.name": "inventory only: every connection "
    "parameter comes solely from the .dsn secret (manifest 9); storage "
    "of the label is allowed by manifest 13.2",
    "ru.3ops.discovery.database.user": "inventory only, see database.name",
    "ru.3ops.discovery.database.sslmode": "inventory only, see database.name",
    "ru.3ops.discovery.logs.stream-policy": "reserved: manifest 8 defines "
    "no stream-policy family yet, loki.source.docker does not split "
    "stdout/stderr streams",
    "ru.3ops.discovery.logs.redaction-profile": "reserved by manifest 10.3.5",
    "ru.3ops.discovery.logs.drop-profile": "reserved by manifest 10.3.5",
    "ru.3ops.discovery.otel.enabled": "declarative domain: the OTLP "
    "receiver cannot correlate a push with the container that declared "
    "the label (manifest 10.5)",
    "ru.3ops.discovery.otel.protocol": "declarative, see otel.enabled",
    "ru.3ops.discovery.otel.service": "declarative, see otel.enabled; "
    "service identity comes from the OTLP resource attributes",
    "ru.3ops.discovery.otel.traces": "declarative, see otel.enabled; the "
    "receiver has no traces output, so trace pushes fail loudly",
    "ru.3ops.discovery.otel.metrics": "declarative, see otel.enabled",
    "ru.3ops.discovery.otel.logs": "declarative, see otel.enabled",
    "ru.3ops.discovery.ipmi.enabled": "declarative domain: Alloy has no "
    "native IPMI component, so the domain is a special case of metrics -- "
    "scraping an external ipmi_exporter -- and ships no pipeline that "
    "could read the label (manifest 10.7)",
    "ru.3ops.discovery.ipmi.address": "declarative, see ipmi.enabled; the "
    "BMC address is consumed by the exporter, not by Alloy",
    "ru.3ops.discovery.ipmi.module": "declarative, see ipmi.enabled",
    "ru.3ops.discovery.ipmi.secret-id": "declarative, see ipmi.enabled; "
    "BMC credentials are read by the exporter, not by Alloy",
    "ru.3ops.discovery.ipmi.profile": "declarative, see ipmi.enabled; it "
    "names a manifest 8.2 scrape profile, and the domain has none of its own",
}

#: All manifest 8.2 scrape profiles are implemented in 020_metrics.
SCRAPE_PROFILES_UNIMPLEMENTED: dict[str, str] = {}

LOG_PROFILES_UNIMPLEMENTED: dict[str, str] = {
    "app-type-1-v1": "named example of a specialized pipeline, not a "
    "shipped profile (manifest 8.3)",
    "nginx-json-v1": "specialized pipeline example, not shipped "
    "(manifest 8.3)",
}

#: All manifest 10.2 database types are implemented as of phase 2.
DB_TYPES_UNIMPLEMENTED: dict[str, str] = {}

#: All manifest 8.4 database profiles are handled in 030: every pipeline
#: validates the profile label fail-closed and drives its exporter's
#: collection scope from it (standard-v1 = the exporter's defaults).
DB_PROFILES_UNHANDLED: dict[str, str] = {}

#: All manifest 8.2 scrape profiles are implemented in 035_blackbox.
BLACKBOX_SCRAPE_PROFILES_UNIMPLEMENTED: dict[str, str] = {}

#: Probe families the manifest 10.4 prose promises ("HTTP, TCP, ICMP и TLS
#: checks") but the reference exporter allowlist does not ship. All four
#: families ship now, so this is empty; the module set stays open-ended in
#: the manifest (no closed normative list), so the one-sided table only
#: guards disjointness with the shipped set.
BLACKBOX_MODULES_UNIMPLEMENTED: dict[str, str] = {}

#: The reference ships exactly one snmp profile (snmp-standard-v1); the
#: manifest 8.5 declares no others, so this is empty. It exists so the
#: both-ways gate has a symmetric partner and widening 8.5 later is a visible
#: diff.
SNMP_SCRAPE_PROFILES_UNIMPLEMENTED: dict[str, str] = {}

#: Modules the manifest 10.6 example list mentions but the reference relabel
#: keep-rule does not accept; adding one is an overlay/extension. The snmp
#: allowlist is one-sided (modules live in the exporter's built-in snmp.yml,
#: no in-repo source of truth), so this only guards disjointness, and
#: test_module_gap_entries_appear_in_manifest retires phantom entries
#: (cisco_device was deliberately cut from the manifest, see the 0.1.x
#: changelog, so its entry left this table with it).
SNMP_MODULES_UNIMPLEMENTED: dict[str, str] = {}

#: Table rows a translation carries beyond its Russian original, keyed by
#: the translated file. README.md documents docs/manifest.md itself, a row
#: the Russian README has no reason to carry. test_translation.py demands
#: exact equality against this number in both directions, so a phantom
#: entry fails the gate just as a new undeclared row does.
TRANSLATION_EXTRA_TABLE_ROWS: dict[str, int] = {"README.md": 1}

#: Config files that produce no series or streams of their own, and are
#: therefore exempt from the manifest 6.1 provenance check. Everything
#: else in alloy/ and alloy-optional/ must attach host and collector;
#: test_provenance.py derives the checked set by subtracting this table
#: from the file glob, so a new domain file is covered on arrival rather
#: than when someone remembers to list it.
NOT_SERIES_PATHS: dict[str, str] = {
    "010_discovery.alloy": "discovery only: exports targets, and the "
    "domain files attach provenance to what they build from them",
    "050_log-profiles.alloy": "parses line content into structured "
    "metadata; the stream labels are attached by 040 upstream",
    "060_otel.alloy": "the shared OTLP receiver is static and has no "
    "Docker metadata, so it cannot produce container/host provenance -- "
    "documented as an explicit exemption by manifest 10.5",
    "090_outputs.alloy": "the write path: remote_write and loki.write "
    "forward what the domains already labelled",
}
