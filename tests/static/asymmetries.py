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

#: Manifest 14.1 default cells that describe an expression rather than a
#: literal: variable -> (manifest cell text, expression in the config's
#: coalesce). test_env_vars.py maps the cell through this table instead of
#: comparing strings.
ENV_DEFAULT_EXPRESSIONS: dict[str, tuple[str, str]] = {
    "RU_3OPS_DISCOVERY_HOSTNAME": (
        "hostname коллектора",
        "constants.hostname",
    ),
}

#: Config files that produce no series or streams of their own, and are
#: therefore exempt from the manifest 6.1 provenance check. Everything
#: else in implementations/alloy/ must attach host and collector;
#: test_provenance.py derives the checked set by subtracting this table
#: from the file glob, so a new domain file is covered on arrival rather
#: than when someone remembers to list it.
NOT_SERIES_PATHS: dict[str, str] = {
    "010_discovery-scrape.alloy": "discovery only: exports targets, and the "
    "domain files attach provenance to what they build from them",
    "011_discovery-logs.alloy": "discovery only: exports targets, and the "
    "logs domain attaches provenance to what it builds from them",
    "050_log-profiles.alloy": "parses line content into structured "
    "metadata; the stream labels are attached by 040 upstream",
    "060_otel.alloy": "the shared OTLP receiver is static and has no "
    "Docker metadata, so it cannot produce container/host provenance -- "
    "documented as an explicit exemption by manifest 10.5",
    "090_output-metrics.alloy": "the metrics write path: remote_write "
    "forwards what the domains already labelled",
    "091_output-logs.alloy": "the logs write path: loki.write forwards "
    "what the domains already labelled",
}

#: Manifest sections outside 14.4 that still name the reference
#: implementation (Alloy, its components or River functions), each with
#: the stage-3 task that neutralizes it or the reason it stays (the
#: section 1 pointer and the section 14 registry name the agent by
#: design).
#: test_manifest_neutrality.py demands equality with the scanner's
#: findings in both directions on docs/manifest.ru.md, and bounds
#: docs/manifest.md by the same table, so neutralizing a section forces
#: its entry out. The table only shrinks.
MANIFEST_IMPLEMENTATION_MENTIONS: dict[str, str] = {
    "1": "pointer to the reference implementation",
    "14": "registry names the agent",
}

#: Contract rules the reference does not meet: "<section>/<items>" ->
#: reason. Each unmet rule has a 14.4.4 bullet that names this table
#: (tests/static/test_rules_unmet.py); a rule stays a MUST in the contract.
MANIFEST_RULES_UNMET: dict[str, str] = {
    "10.3.4/3-4": "the reference replaces an unknown log profile with "
    "raw-v1 in a discovery.relabel rule; relabel rules cannot write to the "
    "collector's own log (item 3) or increment a metric (item 4), so "
    "neither is emitted (manifest 14.4.4).",
}

#: Database type x profile cells (manifest 10.2 x 8.4) the series catalog
#: does not carry: a catalog cell is snapshotted from an e2e container,
#: and no e2e container runs these pairs. test_series_catalog.py demands
#: that catalog cells and this table partition the full product, and that
#: every key is a real pair, so adding a container forces its entry out.
SERIES_CELLS_UNCATALOGUED: dict[tuple[str, str], str] = {
    ("database", "mysql/basic-v1"): "no e2e container runs mysql",
    ("database", "mysql/standard-v1"): "no e2e container runs mysql",
    ("database", "mysql/extended-v1"): "no e2e container runs mysql",
    ("database", "postgres/standard-v1"): (
        "the e2e postgres containers declare basic-v1 and extended-v1"
    ),
    (
        "database",
        "mariadb/basic-v1",
    ): "the e2e mariadb runs the default standard-v1",
    (
        "database",
        "mariadb/extended-v1",
    ): "the e2e mariadb runs the default standard-v1",
    (
        "database",
        "redis/basic-v1",
    ): "the e2e redis runs the default standard-v1",
    (
        "database",
        "redis/extended-v1",
    ): "the e2e redis runs the default standard-v1",
    (
        "database",
        "mongodb/basic-v1",
    ): "the e2e mongodb runs the default standard-v1",
    (
        "database",
        "mongodb/extended-v1",
    ): "the e2e mongodb runs the default standard-v1",
}

#: Catalog series an implementation is allowed not to deliver, or to deliver
#: without the cataloged identity labels, as (implementation, domain, cell,
#: series) -> reason. test_series_parity.py subtracts the rows of the
#: collector that serves the cell's domain (`Stack.collector`) from the
#: problems it finds; test_implementation_gaps.py keeps every row inside its
#: implementation's manifest 14 registry row. Empty: the reference and
#: vmagent deliver every cell on both storage backends.
SERIES_PARITY_GAPS: dict[tuple[str, str, str, str], str] = {}

_VMAGENT_NETWORK_FILTER = (
    "vmagent v1.154.1 sends the docker_sd `filters` to GET /networks as "
    "well as to GET /containers/json, so the contract label filter matches "
    "no network and the network metadata is empty; __meta_docker_network_ip "
    "comes from the container object and stays. Seen on a live probe: "
    "discoveredLabels carried only __meta_docker_network_ip, and the proxy "
    "log showed GET /networks?filters=...ru.3ops.discovery.enabled... . "
    "Targets are unaffected: the rules read only the IP."
)

#: Docker discovery meta labels an implementation never produces:
#: (implementation, domain, label) -> reason; `<name>` stands for any
#: suffix. test_implementation_gaps.py demands that the implementation's
#: config reads none of them and that the domain is in its registry row.
DISCOVERY_META_LABELS_ABSENT: dict[tuple[str, str, str], str] = {
    ("vmagent", "metrics", label): _VMAGENT_NETWORK_FILTER
    for label in (
        "__meta_docker_network_id",
        "__meta_docker_network_name",
        "__meta_docker_network_scope",
        "__meta_docker_network_internal",
        "__meta_docker_network_ingress",
        "__meta_docker_network_label_<name>",
    )
}

#: Non-indexed log fields a store adds on its own, per e2e backend:
#: backend -> field -> reason and source. Anything Alloy adds beyond the
#: manifest 8.3 table is a reference defect and never goes here.
STORE_DERIVED_LOG_FIELDS: dict[str, dict[str, str]] = {
    "prometheus-loki": {
        "detected_level": "Loki 3.x adds it to every line at ingest "
        "(`unknown` when none is detected; "
        "limits_config.discover_log_levels, default true). "
        "Source: `docker run --rm grafana/loki:3.6.12 -help | "
        "grep -A2 discover-log-levels`; no file under implementations/alloy/ "
        "names it; "
        "seen as {'detected_level': 'unknown'} on a raw-v1 record.",
    },
    "victoria": {},
}

#: Behaviour a second implementation of the logs domain does not match,
#: as (implementation, domain, topic) -> reason with its live source.
#: test_implementation_gaps.py keeps every row inside its implementation's
#: manifest 14 registry row. The table is the registry of those
#: divergences; the mechanisms are described in the implementation's README
#: ("Differences from the reference").
LOGS_IMPLEMENTATION_GAPS: dict[tuple[str, str, str], str] = {
    ("vector", "logs", "10.3.4 item 4 error metric"): (
        "The config increments no metric and has no metrics output. The "
        "unknown-profile fallback to raw-v1 and the WARN of item 3 are "
        "met. Mechanism: "
        'implementations/vector/README.md, "Unknown profile".'
    ),
    ("vector", "logs", "10.3.4 item 3 warning rate limit"): (
        "The WARN naming the container and the profile is rate-limited per "
        "call site (rate_limit_secs: 60), not per container: a second "
        "container with an unknown profile within the window is collected "
        "as raw-v1 but not named. Seen on a live run: two misconfigured "
        "containers produced one WARN and one `is being suppressed` line."
    ),
    ("vector", "logs", "own container excluded by hostname"): (
        "docker_logs skips the container whose ID starts with Vector's own "
        "hostname (at least 6 characters), and Docker's default hostname is "
        "the short ID, so Vector does not collect its own logs unless the "
        "container sets `hostname:`. The e2e overlay sets it. Source: "
        "src/sources/docker_logs/mod.rs v0.60.0 `exclude_self`; spike R5 "
        "log line `Excluded self container`."
    ),
    ("vector", "logs", "lines lost while Vector is down"): (
        "docker_logs keeps no read positions: it reads every container, "
        "including one that started earlier, only from Vector's own start "
        "(since = now - 1s). Lines written while Vector is stopped, and "
        "lines a container wrote before Vector started, never reach the "
        "store; the reference resumes from its positions file. Under "
        "Vector the secret-redaction e2e check therefore sees only lines "
        "written after Vector's start: reduced coverage, not a gap in the "
        "check. Source: src/sources/docker_logs/mod.rs v0.60.0 "
        "`log_since`. Mechanism: implementations/vector/README.md, "
        '"Lines written while Vector is down are lost".'
    ),
    ("vector", "logs", "docker refresh interval not read"): (
        "RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL has no effect: "
        "docker_logs follows the Docker event stream and picks up a "
        "container when it starts, with no list to refresh."
    ),
    ("vector", "logs", "logfmt line over 64 KiB"): (
        "A logfmt line longer than 64 KiB gives no structured metadata in "
        "the reference (its line scanner stops at that size) and is parsed "
        "whole by Vector. Seen live: `level=info k=y...(70022 chars) "
        "status=9` gave {} on Alloy v1.21.2 and level and status on Vector "
        "0.60.0. Mechanism: implementations/vector/README.md, "
        '"logfmt parsing".'
    ),
    ("vector", "logs", "logfmt lone surrogate escape"): (
        'A quoted value `"\\ud800"` gives U+FFFD in the reference and the '
        "raw text `\\ud800` in Vector, whose JSON unescaping refuses a "
        'lone surrogate. Seen live on `level="\\ud800" status=3`. '
        'Mechanism: implementations/vector/README.md, "logfmt parsing".'
    ),
}
