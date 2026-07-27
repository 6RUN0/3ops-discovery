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
