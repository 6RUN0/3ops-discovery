# 3ops Discovery Manifest

**Status:** Draft  
**Specification version:** `0.2.0`  
**Namespace:** `ru.3ops.discovery.*`  
**Change history:** [CHANGELOG.md](../CHANGELOG.md)

> **Translation.** The normative contract is the Russian
> [manifest.ru.md](manifest.ru.md): the static gates extract their facts
> from that file and from it alone. This English text is provided for
> readers and is not covered by the gates; on any discrepancy the Russian
> original wins.

## 1. Purpose

`3ops Discovery` is a declarative mini-framework for automatic discovery and configuration of telemetry targets, driven by Docker labels.

A container describes:

- which signals should be collected;
- which integration/exporter type to use;
- where to take the metrics or logs from;
- how to name the target;
- where the implementation should look for secrets;
- which extra labels to attach to the telemetry.

The implementation:

1. discovers containers through the Docker API;
2. filters targets by labels;
3. normalizes the metadata;
4. builds the metrics and logs collection pipeline;
5. sends metrics to a store that accepts Prometheus remote_write (Prometheus, VictoriaMetrics, Mimir);
6. sends logs to Loki or VictoriaLogs;
7. never receives secrets directly from Docker labels.

The contract fixes the labels, the behaviour and the result in the store. It does not fix which agent collects the telemetry or how that agent is configured: the implementations are listed in section [14](#14-implementations). The reference implementation is Grafana Alloy (section [14.4](#144-reference-implementation-alloy)).

## 2. Base model

```text
container Docker labels
    |
    v
domain (section 10)
    |
    v
domain implementation (section 14)
    |
    v
output protocol (section 14.2)
    |
    v
store
```

Labels assign a container to domains. Each domain on a host is served by one implementation; it collects the domain's data and sends it over the output protocol to the store: metrics over Prometheus remote_write, logs over a protocol the log store accepts. The snmp domain and the host domains take their targets from elsewhere than labels: snmp from the device file, the host domains from the host itself (section [10](#10-domains)).

## 3. Namespace and naming convention

Every label of the mini-framework starts with:

```text
ru.3ops.discovery.
```

The general form:

```text
ru.3ops.discovery.<domain>.<key>
```

Global keys may omit the `<domain>` part:

```text
ru.3ops.discovery.enabled
ru.3ops.discovery.version
```

### 3.1. Naming rules

- Dots express hierarchy.
- Key names are written in lowercase.
- Compound names inside a single key use a hyphen: `secret-id`.
- One meaning must not have several spellings.
- Passwords, tokens, private keys and full DSNs must never be stored in labels.
- Label values are always strings.

Example:

```yaml
labels:
  ru.3ops.discovery.enabled: "true"
  ru.3ops.discovery.database.type: "postgres"
  ru.3ops.discovery.database.secret-id: "postgres-orders"
```

## 4. Label key normalization

Two label keys that coincide after replacing `.` and `-` with `_` are forbidden: of such spellings the contract declares only one.

The rule exists because implementations normalize keys. An example is Docker service discovery in Prometheus: a container label reaches the relabeling rules as a meta label, and dots, hyphens and other unsuitable characters in its name are replaced with `_`. The Docker label

```text
ru.3ops.discovery.database.secret-id
```

becomes part of the meta label name as:

```text
ru_3ops_discovery_database_secret_id
```

Because of that, the following labels collide after normalization:

```text
ru.3ops.discovery.database.secret-id
ru.3ops.discovery.database.secret.id
```

Only the first spelling may be used.

## 5. Global labels

### `ru.3ops.discovery.enabled`

The mandatory flag that opts a container into discovery for the metrics, database and blackbox domains: without `enabled == true` a container does not enter the pipeline of those domains.

Declaring and reading are different things, and they do not coincide everywhere. For the otel and ipmi domains the label is declared by the same rule, but implementations do not read it: the OTLP receiver of otel is shared and static and cannot relate a push to the container that declared the label (section [10.5](#105-domain-otel)), while ipmi has no domain pipeline at all: the external exporter is scraped as a target of the metrics domain (section [10.7](#107-domain-ipmi)). For those two domains `enabled` is an inventory declaration of intent rather than a control flag; the contract cannot require an implementation to read it.

Exception: the `logs` domain collects stdout/stderr of every container by default and does not require this label (see section [10.3.1](#1031-default-collection-policy)). The `snmp` domain is driven by a device file rather than by Docker labels (section [10.6](#106-domain-snmp)), so the global `enabled` does not apply to it.

Allowed values:

```text
true
false
```

### `ru.3ops.discovery.version`

The version of the label contract.

Example:

```yaml
ru.3ops.discovery.version: "0.2"
```

If the label is absent, the contract version the implementation accepts by default applies.

In version `0.2` the label is reserved: the implementation processes every container by the `0.2` rules, whatever its value. Version validation will arrive together with the first change that alters label semantics (section [7](#7-contract-versioning)).

### `ru.3ops.discovery.instance`

The logical name of the instance.

Used as the primary `instance` label whenever a domain-specific value is absent.

Example:

```yaml
ru.3ops.discovery.instance: "orders-postgres"
```

### `ru.3ops.discovery.environment`

The environment. The list is open and is not validated by the configuration (with untrusted neighbours on the host it is constrained by an allowlist rule, section [13.5](#135-trust-in-labels)); the recommended values are:

```text
production
staging
testing
development
```

### `ru.3ops.discovery.team`

The team or the owner of the service.

Example:

```yaml
ru.3ops.discovery.team: "payments"
```

## 6. Common telemetry labels

### 6.1. Labels added by the implementation

The implementation must add the following labels to metrics and logs whenever they are available:

```text
instance
environment
team
container
compose_project
compose_service
host
collector
```

The value of `collector` is the implementation name from the registry of section [14](#14-implementations): it shows which implementation collected a series or a line.

Duplication of semantically identical labels must be avoided:

```text
env and environment
service and service_name
container and container_name
```

The recommended canonical names:

```text
environment
service_name
instance
container
team
compose_project
compose_service
```

The log path adds `service_name`, `log_profile` and `source` to this set; the full list of permitted indexed log fields is in section [6.2](#62-log-fields), which governs cardinality rather than composition. There is no single place listing every emitted label, by construction: metrics and logs have different sets, and section [6.2](#62-log-fields) is the normative source for logs.

The `container` label comes from the Docker engine metadata and `host` from the deployment parameter `RU_3OPS_DISCOVERY_HOSTNAME`, which defaults to the collector hostname; neither is set by container labels, so a container cannot forge their values. The remaining labels are declared by the container itself (see section [13.5](#135-trust-in-labels)). For logs the set is additionally constrained by the allowlist of section [6.2](#62-log-fields).

The `instance` label belongs to metrics; for logs its counterpart is `service_name` (see section [10.3.5](#1035-labels)). The analogy is incomplete and must not be leaned on as a rule: `service_name` is derived from `logs.service` alone, whereas the global `instance` does not extend to logs.

Series identity per domain. Dashboards and alert rules bind to exactly these values, so they are part of the contract rather than an implementation detail:

| Domain | `job` | `instance` | Additionally |
|---|---|---|---|
| metrics | from `metrics.job` (mandatory) | the target address; overridden by `instance` | -- |
| database | the database type (`database.type`) | `database.instance`, else the global `instance`, else `secret-id` | -- |
| blackbox | the constant `blackbox` | the probe address (`blackbox.address` or the container address) | `module` -- the probe type |
| snmp | the constant `snmp` | the device address | `device` -- the device name; `snmp_profile` -- the profile name of section [8.5](#85-snmp-profiles) |
| host-metrics | the constant `integrations/unix` - the exporter label | the collector hostname | - |
| container-metrics | the constant `integrations/cadvisor` - the exporter label | the collector hostname | `container` - the container name; `compose_project`, `compose_service` - from the Compose labels |

In the host-metrics and container-metrics domains `job` and `instance` are a deliberate gap: `job` is the exporter constant rather than a value from labels, and `instance` is the collector hostname (the exporter default, not set by `RU_3OPS_DISCOVERY_HOSTNAME`). It equals `host` only while the parameter is unset or empty; queries that join these domains with the others join on `host`, not on `instance`. These domains have one target per collector, and that target has no address.

The blackbox domain is a documented exception to the global `instance` rule of section [5](#5-global-labels): for a probe the instance is the probe target itself, so the global value does not apply here and does not override the address. An `instance` declared on a container with a blackbox probe belongs to its own metrics, not to its probes.

### 6.2. Log fields

The fields of a log record fall into two classes: indexed fields define the stream, and the store builds its index on them; non-indexed fields are kept with the line without an index. Only low-cardinality fields may be indexed:

```text
service_name
environment
team
container
compose_project
compose_service
log_profile
host
collector
source
```

Indexed fields are built solely from discovery metadata and container labels. Fields extracted from the content of a line are never promoted into indexed fields: the content is under the control of the application, and such promotion opens the door to label spoofing and unbounded stream cardinality. By default `level` is not indexed (it is absent from the allowlist above and stays in the list below); a deployment may promote it only if it normalizes the value to a bounded set and extends the allowlist.

The following fields must stay inside the line or in non-indexed fields:

```text
level
status
request_id
trace_id
user_id
session_id
client_ip
email
full_path
pid
```

Stores name the classes in their own terms:

| Store | Indexed fields | Non-indexed fields |
|---|---|---|
| Loki | stream labels | structured metadata |
| VictoriaLogs | stream fields | ordinary record fields |

Non-indexed fields do not affect cardinality, but the size of their values is controlled by the application. Size is bounded by the store's limits.

#### 6.2.1. Loki

For filtering by level, Loki 3.x computes `detected_level` on its own from the line content and structured metadata.

The size of structured metadata is bounded by the Loki limit `max_structured_metadata_size`.

Structured metadata requires Loki 3.x with schema v13 (TSDB) and `allow_structured_metadata` enabled. On an older schema the push is rejected as a whole: profiles that parse silently stop delivering lines while `raw-v1` keeps working - on partial log loss this is the first thing worth checking.

## 7. Contract versioning

The contract version is carried by:

```yaml
ru.3ops.discovery.version: "0.2"
```

Rules:

- patch changes do not alter the meaning of existing labels;
- minor changes may add new optional labels;
- major changes may alter semantics or remove fields;
- starting from the first change that alters label semantics, the implementation must state the supported versions explicitly (in `0.2` the check is reserved, see section [5](#5-global-labels)).

The label versions the meaning of the labels, not the specification text: its major and minor move by the rules above, not after the major.minor in the document header. Patch changes by definition do not alter label semantics, so the label carries the major and minor parts only. The format is `<major>.<minor>`, both parts decimal without leading zeros: `^\d+\.\d+$`. The values `0.2.0`, `v0.2` and `0.2-rc1` do not conform; the specification version in the header of this document is a full SemVer and deliberately does not share the format of this label.

The label value moves only together with a change in the meaning of the labels. A new optional label changes the meaning of the label set, so it moves the value to the next minor version. A minor version of the specification text that leaves the meaning of the labels intact does not touch the label value: containers with `ru.3ops.discovery.version: "0.2"` stay valid.

Behaviour on an unsupported version is undefined in `0.2` because the check is reserved: an implementation must accept any value and may not drop a target based on it. When the check does arrive, it must obey the rule of the logs domain (section [10.3.4](#1034-unknown-profile)): logs are not lost under any version, and dropping by version is admissible only for domains with fail-closed semantics.

## 8. Profiles

### 8.1. General rules

A profile is the name of a predefined, versioned set of settings. The manifest defines the profile allowlist of every domain (sections [8.2](#82-scrape-profiles)-[8.5](#85-snmp-profiles) and [10](#10-domains)).

- The value of `*.profile` is picked only from the allowlist defined by the manifest; the implementation of a domain must support the whole allowlist of that domain.
- The label is neither a DSL nor a pipeline programming language: arbitrary values and stage lists are not supported.
- A profile name must carry a version: the suffix `-vN`, with the full name made of `[a-z0-9-]`.
- Changing a profile may affect labels, cardinality, timestamps, alert rules and Grafana queries, so incompatible changes require a new profile name.

A versioning example:

```text
orders-api-v1
orders-api-v2
```

A forbidden variant:

```yaml
ru.3ops.discovery.logs.profile: "json,logfmt,raw"
```

### 8.2. Scrape profiles

The scrape cadence of a target is set by a profile from a bounded set of versioned profiles. Arbitrary interval/timeout values from labels are not supported.

The base profiles:

```text
fast-v1:
  interval: 15s
  timeout: 10s

normal-v1:
  interval: 30s
  timeout: 10s

slow-v1:
  interval: 60s
  timeout: 15s
```

They are selected through the labels `ru.3ops.discovery.metrics.profile` and `ru.3ops.discovery.blackbox.profile`; the default is `normal-v1`.

### 8.3. Log profiles

A log profile describes the complete processing pipeline:

```text
parser
multiline
timestamp
labels
structured metadata
redaction
drop rules
message normalization
```

The list describes the scope of the notion of a log profile, not the obligations of every profile: the base profiles below implement the parser, multiline and structured metadata parts. The timestamp stage is not implemented in the reference: the record time is the docker timestamp of the line (the moment the application wrote it to stdout/stderr); a timestamp inside the line content is not parsed.

The base profiles:

```text
raw-v1
  Apply no structural parser.
  Keep the original line.

generic-json-v1
  Best-effort JSON parsing.
  On error keep the original line.

generic-logfmt-v1
  Best-effort logfmt parsing.
  On error keep the original line.

mixed-v1
  Try to detect JSON or logfmt for each line.
  Keep unrecognized lines raw.

app-type-1-v1
  A placeholder name for a specialized pipeline;
  real profiles are named after the application family.

nginx-json-v1
  An example of a specialized pipeline for JSON access logs;
  not part of the reference (same as app-type-1-v1).

java-stacktrace-v1
  A multiline pipeline for Java stack traces.

python-stacktrace-v1
  A multiline pipeline for Python tracebacks.
```

Extracted fields. The set of fields that reach structured metadata is part of the profile definition rather than an implementation detail: the versioning promise of section [8.1](#81-general-rules) means two independent implementations of one profile name produce the same metadata. Otherwise `generic-json-v1` from one vendor and from another are different things under one name.

| Profile | Fields in structured metadata |
|---|---|
| `raw-v1` | -- |
| `generic-json-v1` | `level`, `status`, `trace_id`, `request_id` |
| `generic-logfmt-v1` | `level`, `status`, `trace_id`, `request_id` |
| `mixed-v1` | `level`, `status`, `trace_id`, `request_id` (both branches) |
| `java-stacktrace-v1` | -- |
| `python-stacktrace-v1` | -- |

The sets of `generic-json-v1` and `generic-logfmt-v1` coincide deliberately: the profiles differ in input format, not in what is extracted. A field absent from a line simply does not appear -- that is not a parse error.

The premise of the multiline profiles. `java-stacktrace-v1` and `python-stacktrace-v1` recognize the start of a record by an ISO-8601 timestamp prefix (`2026-07-27T12:00:00`, or with a space instead of `T`) at the beginning of the line. An application that does not print such a prefix produces NOT A SINGLE line recognized as a start: the whole stream is glued into blocks bounded by `max_lines` (128), whose boundaries have nothing to do with the content. This is a limitation of the profile rather than a failure: an application without an ISO-8601 prefix is served by `raw-v1` or by a specialized profile with an anchor of its own. The raw fallback of section [10.3.3](#1033-raw-fallback) does not help here -- it is meant for a parser error, and gluing is not an error.

### 8.4. Database profiles

```text
basic-v1
standard-v1
extended-v1
```

The profiles make it possible to control the load without accepting arbitrary settings from labels. They are selected through `ru.3ops.discovery.database.profile`; the default is `standard-v1`.

A database profile governs the collection volume - which series are produced for the database - rather than the scrape cadence: the scrape profiles of section [8.2](#82-scrape-profiles) apply to the `metrics` and `blackbox` domains only. The cadence of the database domain is fixed and not chosen by a profile: `interval: 60s`, `timeout: 10s`. The value is set by the contract, and the implementation states it explicitly: a value a consumer observes cannot be the default of a third-party product, which moves when that product is updated. A value outside the allowlist drops the target entirely (fail-closed) - as in the metrics and blackbox domains. The `logs` domain is the single exception and the only domain where an unknown profile does not drop the target: logs are not lost, `raw-v1` applies (section [10.3.4](#1034-unknown-profile)). The fail-closed rule holds for every domain except logs.

The content of a profile is stated in series. For the type/profile pairs present in the series catalog [`docs/series/database.yaml`](series/database.yaml) (section [14.3](#143-series-catalog) names the missing ones), the catalog lists the series the profile must produce (`present`) and the series it must switch off (`absent`). For example, postgres on `basic-v1` does not produce `pg_settings_max_connections`, and on `extended-v1` it produces `pg_long_running_transactions` and `pg_database_wraparound_age_datfrozenxid_seconds`. An incompatible change of the series of a profile requires a new profile name (section [8.1](#81-general-rules)).

For every pair, the ones missing from the catalog included, the profiles differ by series families. `up`, `<type>_up` and the series about the exporter itself (scrape duration and success) are produced on every profile, and the rules below do not restrict them.

- `postgres`: `basic-v1` does not produce `pg_settings_*`; `extended-v1` adds to `standard-v1` the families `pg_database_wraparound_*`, `pg_long_running_transactions*`, `pg_process_idle_seconds*` (when idle connections exist) and `pg_statio_user_indexes_*` (when user indexes exist).
- `mysql`/`mariadb`: of the series about the server, `basic-v1` produces only the series of the server status and server variables groups (`SHOW GLOBAL STATUS`, `SHOW GLOBAL VARIABLES`): `mysql_global_status_*`, `mysql_global_variables_*` and the derived `mysql_version_info`, `mysql_transaction_isolation`, `mysql_galera_*`; `extended-v1` adds to `standard-v1` the families `mysql_engine_innodb_*`, `mysql_info_schema_processlist_*` (when server threads other than the exporter connection exist) and `mysql_info_schema_auto_increment_column*` (when tables with an `AUTO_INCREMENT` column exist).
- `redis`: `basic-v1` produces only `redis_*` series; `extended-v1` adds to `standard-v1` the client list series `redis_connected_client_*` (`CLIENT LIST`) and `redis_total_system_memory_bytes`.
- `mongodb`: of the series about the server, `basic-v1` produces only diagnostic data series (`getDiagnosticData`); `extended-v1` produces the same series as `standard-v1`.

The load is monotonic: basic <= standard <= extended. The order is not strict: adjacent profiles of one type may produce the same series. Every profile, `extended-v1` included, works on a database without extensions or special server settings.

### 8.5. SNMP profiles

A domain-wide allowlist of versioned snmp profiles. The differentiator is the raised `timeout` (30s) for slow devices; [8.2](#82-scrape-profiles) is shared between `metrics` and `blackbox` and offers no such timeout, which is why the snmp profiles form a family of their own. The reference ships a single profile; it applies to the whole snmp scrape (the file provider yields one exporter and one scrape).

SNMP profiles:

```text
snmp-standard-v1:
  interval: 60s
  timeout: 30s
```

Per-device selection and more than one profile are documented future work.

## 9. Secret contract

The label carries a logical identifier only:

```yaml
ru.3ops.discovery.database.secret-id: "postgres-orders"
```

The implementation builds the path:

```text
/run/alloy-secrets/postgres-orders.dsn
```

The file content:

```text
postgresql://alloy_monitor:secret@postgres-orders:5432/postgres?sslmode=disable
```

The content format of `.dsn` depends on the database type:

| Type | Format |
|---|---|
| `postgres` | `postgresql://<user>:<password>@<host>:<port>/<db>?sslmode=...` |
| `mysql`, `mariadb` | `<user>:<password>@(<host>:<port>)/` (go-sql-driver DSN) |
| `redis` | `<host>:<port>` in `.dsn`; the password lives in a separate `<secret-id>.redispass` file |
| `mongodb` | `mongodb://<user>:<password>@<host>:<port>` |

Redis is the exception: the address (`host:port`) is non-secret and is stored in `.dsn`, while the password goes into a separate secret file `<secret-id>.redispass`.

Requirements:

- the file is readable only by the user the implementation runs as;
- the directory is mounted read-only;
- the implementation hides the value of a file with credentials: its API and exports show a marker instead of the value;
- `secret-id` is validated by a regular expression;
- `secret-id` must not contain `/`, `..`, spaces or shell characters.

The allowed pattern:

```regex
^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$
```

The contract is shared by the label-driven domains; only the per-domain file suffix differs (snmp, being a file provider, is the exception -- see [10.6.1](#1061-snmp-auth)):

```text
database  /run/alloy-secrets/<secret-id>.dsn   (+ <secret-id>.redispass for type=redis)
snmp      /run/alloy-secrets/snmp_auths.yaml  (exception, a single file -- see 10.6.1)
ipmi      /run/alloy-secrets/<secret-id>.ipmi
```

The `/run/alloy-secrets` directory is the default; it is configured by the `RU_3OPS_DISCOVERY_SECRETS_DIR` variable (section [14.1](#141-environment-parameters)).

The identifier validation rules and the read-only mount are identical across domains; hiding the value is mandatory for files with credentials (the address-only redis `.dsn` is non-secret by construction, see above, and its value is not hidden). The requirements for path traversal protection are described in section [13.4](#134-secret-path-traversal).

The `secret-id` space is a single trust domain within the host: the contract does not bind a container to a particular secret, and any container with a valid label may reference any existing secret file. Only secrets meant for the containers of that host should be placed into its secret directory; use a `secret-id` prefix convention to separate teams. Prefixes are an operator convention only: the implementation does not check them, and technically every secret file on the host is reachable by every container of that host. A consequence of the same trust model: a container can determine whether a secret file exists by declaring the corresponding `secret-id` and observing whether an exporter appears; the content of the secret is not disclosed. Binding `secret-id` to a container identity is out of scope for version `0.2` (section [16](#16-out-of-scope)).

A missing secret file: the blast radius. `secret-id` arrives from an untrusted input, so how far the failure spreads when it points at a file that does not exist matters. The contract does not promise that the failure stays within one container: the radius depends on the implementation and may take in other targets of the same collector (the radius of the reference is in section [14.4.4](#1444-how-the-reference-fulfils-the-contract)).

What follows in practice: the right to start containers on a host may include the right to stop collection from other targets on that collector. Monitoring the health of the implementation is mandatory and is not replaced by the contract.

The limits of secret hiding. Hiding is mandatory in the API and the exports of the implementation, but a load error message may quote a fragment of the value read (the `host:port` of someone else's database, say). What follows in practice: the collector's own logs are sensitive and deserve the same handling as secrets: they should not be sent anywhere secrets are not sent (see section [13.2](#132-may-be-stored)).

The snmp domain is the single documented exception to the "one file per `<auth-id>`" convention: its secret is a single `snmp_auths.yaml` file with named profiles inside the YAML (the `auths:` map) rather than one file per `auth-id`. The `secret-id` regular expression above normalizes the secret file names of the label-driven domains and does NOT constrain the profile name referenced by the `auth` field of the file provider (section [10.6.1](#1061-snmp-auth)).

## 10. Domains

The following base domains are defined:

```text
metrics
database
logs
blackbox
otel
snmp
ipmi
```

One container may declare several domains at the same time.

Host domains:

```text
host-metrics
container-metrics
host-logs
```

Host domains are not driven by labels, are off by default and require deployment privileges; in the reference they are the optional files of section [14.4.3](#1443-optional-files).

### 10.1. Domain: metrics

Used when the application already publishes a Prometheus-compatible endpoint.

#### 10.1.1. Labels

| Label | Mandatory | Value |
|---|---:|---|
| `ru.3ops.discovery.metrics.enabled` | Yes | `true` |
| `ru.3ops.discovery.metrics.type` | Yes | `prometheus` |
| `ru.3ops.discovery.metrics.port` | Yes | The port of the metrics endpoint |
| `ru.3ops.discovery.metrics.path` | No | Defaults to `/metrics` |
| `ru.3ops.discovery.metrics.scheme` | No | `http` or `https`, defaults to `http` |
| `ru.3ops.discovery.metrics.job` | Yes | The `job` value |
| `ru.3ops.discovery.metrics.profile` | No | A scrape profile from the allowlist; defaults to `normal-v1` |

Arbitrary interval/timeout values in labels are not supported: scrape parameters are set only by picking a profile (see section [8.2](#82-scrape-profiles)).

`metrics.scheme: https` assumes a certificate the collector trusts through the system trust store: the label contract has no channel for delivering CA material (labels carry strings only -- the same model as the blackbox `tls_connect` module, section [10.4](#104-domain-blackbox)), so an endpoint with a self-signed certificate will not be scraped. TLS trust for internal CAs is an environment customization: a separate scrape pair with `tls_config` (section [14.4.1](#1441-customization)).

#### 10.1.2. RabbitMQ example

```yaml
services:
  rabbitmq:
    image: rabbitmq:4-management
    expose:
      - "15692"

    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.version: "0.2"
      ru.3ops.discovery.instance: "rabbitmq-main"
      ru.3ops.discovery.environment: "production"

      ru.3ops.discovery.metrics.enabled: "true"
      ru.3ops.discovery.metrics.type: "prometheus"
      ru.3ops.discovery.metrics.port: "15692"
      ru.3ops.discovery.metrics.path: "/metrics"
      ru.3ops.discovery.metrics.job: "rabbitmq"
      ru.3ops.discovery.metrics.profile: "fast-v1"
```

The profile sets the scrape cadence of this target; an implementation of the metrics domain supports every base profile of section [8.2](#82-scrape-profiles).

### 10.2. Domain: database

Used for databases that do not publish a Prometheus endpoint themselves.

The supported base types:

```text
postgres
mysql
mariadb
redis
mongodb
```

An implementation of the database domain supports every base type.

`type` denotes the wire protocol and the exporter, not the database vendor. Protocol-compatible builds are labeled with the base type and get no type of their own: Percona Server for MySQL and Percona XtraDB Cluster are `type: mysql`; Percona Server for MongoDB is `type: mongodb` (just like managed databases such as RDS/Aurora MySQL). MariaDB is the exception: it is a type in its own right that shares the mysql exporter, because operators perceive it as a separate product.

`database.port` (and the standard port in its absence) is a target selector rather than a connection parameter: the value is checked against the real private ports of the container (fail-closed: a target with a non-existent port is dropped), whereas the exporter connection address comes entirely from `.dsn` (section [9](#9-secret-contract)). The contract does not require detecting a mismatch between the port in the label and in the DSN.

The standard ports per type (they apply when `database.port` is not set):

| Type | Port |
|---|---|
| `postgres` | 5432 |
| `mysql` | 3306 |
| `mariadb` | 3306 |
| `redis` | 6379 |
| `mongodb` | 27017 |

#### 10.2.1. Labels

| Label | Mandatory | Value |
|---|---:|---|
| `ru.3ops.discovery.database.enabled` | Yes | `true` |
| `ru.3ops.discovery.database.type` | Yes | The database type |
| `ru.3ops.discovery.database.port` | No | The standard port of the type |
| `ru.3ops.discovery.database.instance` | No | The logical name of the database |
| `ru.3ops.discovery.database.name` | No | The database name to connect to |
| `ru.3ops.discovery.database.user` | No | The monitoring user |
| `ru.3ops.discovery.database.secret-id` | Yes | The logical secret identifier (section [9](#9-secret-contract)) |
| `ru.3ops.discovery.database.sslmode` | No | The TLS/SSL setting |
| `ru.3ops.discovery.database.profile` | No | A collection profile from the allowlist; defaults to `standard-v1` |

`database.name`, `database.user` and `database.sslmode` are inventory labels (section [13.2](#132-may-be-stored)): the reference does not read them, every connection parameter comes from `.dsn` alone, and on a mismatch between label and DSN the DSN wins. Series identity: `instance` = `database.instance`, else the global `ru.3ops.discovery.instance` (section [5](#5-global-labels)), else `secret-id` (a synthesized fallback); `job` = `database.type`.

#### 10.2.2. PostgreSQL example

```yaml
services:
  postgres-orders:
    image: postgres:18
    expose:
      - "5432"

    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.version: "0.2"
      ru.3ops.discovery.environment: "production"
      ru.3ops.discovery.team: "orders"

      ru.3ops.discovery.database.enabled: "true"
      ru.3ops.discovery.database.type: "postgres"
      ru.3ops.discovery.database.port: "5432"
      ru.3ops.discovery.database.instance: "orders-db"
      ru.3ops.discovery.database.name: "postgres"
      ru.3ops.discovery.database.user: "alloy_monitor"
      ru.3ops.discovery.database.secret-id: "postgres-orders"
      ru.3ops.discovery.database.sslmode: "disable"
      ru.3ops.discovery.database.profile: "standard-v1"
```

#### 10.2.3. MariaDB example

```yaml
services:
  mariadb-billing:
    image: mariadb:latest
    expose:
      - "3306"

    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.version: "0.2"
      ru.3ops.discovery.environment: "production"
      ru.3ops.discovery.team: "billing"

      ru.3ops.discovery.database.enabled: "true"
      ru.3ops.discovery.database.type: "mariadb"
      ru.3ops.discovery.database.port: "3306"
      ru.3ops.discovery.database.instance: "billing-db"
      ru.3ops.discovery.database.secret-id: "mariadb-billing"
```

### 10.3. Domain: logs

Used for automatic collection and processing of Docker stdout/stderr.

#### 10.3.1. Default collection policy

The logs of every discovered Docker container are collected by default.

```text
the label is absent:
  collect stdout/stderr as raw

ru.3ops.discovery.logs.enabled=true:
  collect stdout/stderr

ru.3ops.discovery.logs.enabled=false:
  explicitly exclude the container from log collection
```

For logs, `ru.3ops.discovery.enabled` is not a precondition. This is deliberate, so that a container without manifest labels is still visible in the log store.

The lines of a container with `ru.3ops.discovery.logs.enabled=false` are not delivered to the store. How to achieve that is up to the implementation: it may leave the stream of such a container unopened, or read the stream and drop the lines before sending.

#### 10.3.2. `logs.profile`

`ru.3ops.discovery.logs.profile` is the name of a predefined pipeline profile from the allowlist (see sections [8.1](#81-general-rules) and [8.3](#83-log-profiles)).

Example:

```yaml
ru.3ops.discovery.logs.profile: "app-type-1-v1"
```

The value must not be an arbitrary list of stages: the implementation picks a profile only from the allowlist of section [8.3](#83-log-profiles).

#### 10.3.3. Raw fallback

For any profile the original line must be preserved whenever the parser fails to read it.

```text
profile=generic-json-v1
  JSON parse success → extract the fields
  JSON parse error   → send raw

profile=app-type-1-v1
  profile match success → apply the pipeline
  no match              → send raw

profile=raw-v1
  always send raw
```

The pipeline must not delete unrecognized lines without a separate, explicitly configured policy.

#### 10.3.4. Unknown profile

If a container names a profile that is absent from the allowlist, the implementation must:

1. keep collecting the logs;
2. apply `raw-v1`;
3. write a diagnostic message into the collector's own log;
4. where possible, increment an internal discovery configuration error metric.

An unknown profile must never cause the loss of a container's logs.

#### 10.3.5. Labels

| Label | Mandatory | Value |
|---|---:|---|
| `ru.3ops.discovery.logs.enabled` | No | Defaults to `true`; `false` disables collection |
| `ru.3ops.discovery.logs.profile` | No | Defaults to `raw-v1` |
| `ru.3ops.discovery.logs.service` | No | The `service_name` value |
| `ru.3ops.discovery.logs.stream-policy` | No | The stdout/stderr processing profile |
| `ru.3ops.discovery.logs.redaction-profile` | No | The identifier of the redaction policy |
| `ru.3ops.discovery.logs.drop-profile` | No | The identifier of the noise filtering policy |

Switching collection off is the only fail-OPEN check in the contract, and deliberately so. The opt-out fires on the literal `false` alone; any other value (`False`, `0`, `no`, a typo) does NOT switch collection off, and logs keep being collected. The direction of failure was chosen in favour of the rule in section [10.3.4](#1034-unknown-profile): a typo in a label must not silently lose logs, whereas collecting more than intended is visible and reversible. Every other label is fail-closed (section [11](#11-validation-rules)).

For version `0.2` a single composite profile is recommended. The additional `stream-policy`, `redaction-profile` and `drop-profile` are reserved for future extension and need not be implemented: their profile families are not defined in section [8](#8-profiles) and the reference does not read these labels.

#### 10.3.6. Examples

An application using logfmt:

```yaml
services:
  orders-api:
    image: example/orders-api:latest

    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.version: "0.2"
      ru.3ops.discovery.instance: "orders-api"
      ru.3ops.discovery.environment: "production"
      ru.3ops.discovery.team: "orders"

      ru.3ops.discovery.logs.profile: "generic-logfmt-v1"
      ru.3ops.discovery.logs.service: "orders-api"
```

A mixed stream:

```yaml
services:
  legacy-worker:
    image: example/legacy-worker:latest

    labels:
      ru.3ops.discovery.logs.profile: "mixed-v1"
      ru.3ops.discovery.logs.service: "legacy-worker"
```

The `mixed-v1` profile may:

1. apply the JSON parser to lines starting with `{`;
2. apply the logfmt parser to lines containing `level=`, `msg=` or `status=`;
3. keep the remaining lines raw.

Format detection is best-effort and must never lead to deletion of the original line. The heuristics admit false positives: a free-text line containing `level=` or `status=` will reach the logfmt parser; on a parse error it is kept raw.

#### 10.3.7. Explicit container exclusion

```yaml
services:
  load-generator:
    labels:
      ru.3ops.discovery.logs.enabled: "false"
```

This is recommended only for:

```text
load generators
temporary test containers
very noisy sidecars
containers with duplicated logs
```

### 10.4. Domain: blackbox

Used for HTTP, TCP, ICMP and TLS checks.

#### 10.4.1. Labels

| Label | Mandatory | Value |
|---|---:|---|
| `ru.3ops.discovery.blackbox.enabled` | Yes | `true` |
| `ru.3ops.discovery.blackbox.module` | Yes | For example `http_2xx`, `tcp_connect`, `icmp`, `tls_connect` |
| `ru.3ops.discovery.blackbox.scheme` | No | `http` or `https`; defaults to `http` |
| `ru.3ops.discovery.blackbox.address` | No | The probe host, without scheme and without port; defaults to the container address |
| `ru.3ops.discovery.blackbox.port` | Yes | The probe port |
| `ru.3ops.discovery.blackbox.path` | No | The HTTP path |
| `ru.3ops.discovery.blackbox.profile` | No | A scrape profile from the allowlist; defaults to `normal-v1` |

The `module` value must belong to the blackbox exporter module allowlist defined by the implementation's configuration. Arbitrary modules from labels are not accepted.

`blackbox.address` carries the host ONLY (`example.com` or an IP): no scheme, no port, no path. The probe target is assembled by the implementation from `address`, `scheme`, `port` and `path`, differently for each module, so a port written into `address` itself would produce a target with two ports. The shape of the probe target depends on the module: HTTP modules receive the URL `scheme://host:port/path`, TCP and TLS modules receive `host:port`, ICMP modules receive the host alone. Every blackbox probe series carries a `module` label with the name of the module used.

For ICMP modules the `blackbox.port` value is not part of the probe itself (ICMP has no port), but the label stays mandatory and goes through the same validation: the declared port must match a real exposed port of the container, otherwise the target is dropped. The rule holds for an external `blackbox.address` too: the port is checked against the private ports of the container itself, so a probe with `address: example.com` and `port: 443` from a container that does not expose port 443 is dropped silently. The consequences of `blackbox.address` for the trust model are covered in section [13.5](#135-trust-in-labels).

ICMP probes need no extra privileges in a typical Docker environment: the standard capability set (`NET_RAW`) or unprivileged ICMP sockets (Docker opens `net.ipv4.ping_group_range` for every group by default) is enough. In hardened environments where `NET_RAW` is dropped and `ping_group_range` is narrowed at the same time, ICMP probes will not work; the way out is to restore `cap_add: [NET_RAW]` or to widen `sysctls: net.ipv4.ping_group_range` on the collector container.

The `tls_connect` module checks that the TLS handshake succeeds and reports certificate expiry metrics (`probe_ssl_earliest_cert_expiry`, `probe_tls_version_info`), but deliberately does not verify the trust chain: the label contract has no channel for delivering CA material into the collector - labels carry strings only. Chain verification for internal CAs is a property of a particular environment: it is done by a separate module with `ca_file` in the blackbox exporter configuration, which is outside the scope of the contract.

#### 10.4.2. Example

```yaml
labels:
  ru.3ops.discovery.enabled: "true"

  ru.3ops.discovery.blackbox.enabled: "true"
  ru.3ops.discovery.blackbox.module: "http_2xx"
  ru.3ops.discovery.blackbox.scheme: "http"
  ru.3ops.discovery.blackbox.port: "8080"
  ru.3ops.discovery.blackbox.path: "/health"
  ru.3ops.discovery.blackbox.profile: "fast-v1"
```

### 10.5. Domain: otel

Used for services that send OTLP telemetry.

The receiver listens on the conventional OTLP ports: `4317` (gRPC) and `4318` (HTTP). The values are fixed by the contract and are not parameterized by an environment variable -- unlike the endpoints of section [14.1](#141-environment-parameters), this is not a deployment value but an address senders know in advance: changing the port would require changing the configuration of every client. A deployment that needs a different port changes the receiver configuration in the implementation - a customization, not a parameter.

#### 10.5.1. Labels

| Label | Mandatory | Value |
|---|---:|---|
| `ru.3ops.discovery.otel.enabled` | Yes | `true` |
| `ru.3ops.discovery.otel.protocol` | Yes | `grpc` or `http` |
| `ru.3ops.discovery.otel.service` | No | The service name |
| `ru.3ops.discovery.otel.traces` | No | `true`/`false` |
| `ru.3ops.discovery.otel.metrics` | No | `true`/`false` |
| `ru.3ops.discovery.otel.logs` | No | `true`/`false` |

This domain mostly documents the expected behavior of the application. An implementation usually runs one shared OTLP receiver rather than a receiver per container.

The `otel.enabled` flag is therefore declarative: it does not govern OTLP ingestion (the receiver is shared and static) but records the intent of the service and serves inventory purposes. The remaining labels of the domain are declarative for the same reason. Traces are outside the perimeter in `0.2`: the reference receiver has no traces output, so a trace export is rejected with an explicit client-side error rather than accepted silently.

The OTLP path is an exception to the provenance of section [6.1](#61-labels-added-by-the-implementation): the shared receiver is static and has no Docker metadata, so it produces no `environment`/`team`/`container` provenance labels. Only an allowlisted set of OTLP resource attributes is promoted into indexed fields (section [6.2](#62-log-fields); in the reference configuration only `service.name` becomes `service_name`); the rest of the identification is supplied by the sending application itself through resource attributes.

### 10.6. Domain: snmp

The only domain not driven by Docker labels: external network equipment (switches, routers) has no container, so targets are enumerated in a file rather than discovered. The domain is opt-in: it is off by default, and a deployment turns it on together with the device file and the auth profile file (section [10.6.1](#1061-snmp-auth)).

The device file (`snmp_targets.yaml`) is a list of entries; every value is stored as a string:

| Field | Mandatory | Value |
|---|---|---|
| `name` | no | A human-readable device name (provenance); when absent the reference substitutes `address` -- the exporter requires `name` on every entry. The value reaches the series as the `device` label (`instance` carries the address) |
| `address` | yes | The `host:port` of the SNMP agent (presence check in relabel) |
| `module` | yes | An snmp_exporter module from the allowlist; in the reference these are `if_mib` (interfaces) and `system` (device identity and uptime: `sysUpTime`, `sysName`) -- an open example list, as in blackbox [10.4](#104-domain-blackbox). One entry means one module; a device with several modules corresponds to several entries with different `name` values |
| `auth` | yes | The name of an auth profile from [10.6.1](#1061-snmp-auth) (presence check; resolved by the exporter) |
| `environment` | no | A provenance label (passed through as non-reserved) |
| `team` | no | A provenance label (passed through as non-reserved) |

The device field is called `auth` -- a reference by name to a profile of the merged `auths:` map; storing such names outside secrets is permitted by section [13.2](#132-may-be-stored). The secret (the SNMP community or the SNMPv3 credentials) lives only in `snmp_auths.yaml` (section [10.6.1](#1061-snmp-auth)), never in the device file.

The [10.7](#107-domain-ipmi) (ipmi) domain is structurally similar but stays a label-driven domain in this phase (a file provider for it is out of scope).

#### 10.6.1. SNMP auth

The auth model of the domain: named profiles in `snmp_auths.yaml`, referenced by name from a device through the `auth` field.

**Version allowlist:** SNMPv2c and SNMPv3. In the file the version is set by the `version` field as a NUMBER, not as the string `v2c`/`v3`: `version: 2` means v2c and `version: 3` means v3. The check is advisory only: the secret file is parsed by the exporter, and discovery never inspects it. The single control point in the repository is the static validator of the auth fixture (`tools/snmp_fixtures.py`, `validate_auths`): `version in {2, 3}` (NOT the exporter range 1..3: SNMPv1 is forbidden by the contract).

**Profile fields per version** (names and types follow `snmp_exporter` v0.29.0, the `Auth` struct):

- `version: 2` (v2c): `community`.
- `version: 3` (v3): `username` and `security_level`, plus the fields required by the chosen level.

**Fields required for v3 per `security_level`** (in addition to `username`):

```text
noAuthNoPriv:
authNoPriv: password | auth_protocol
authPriv: password | auth_protocol | priv_password | priv_protocol
```

**Enums of the v3 fields:**

```text
security_level: noAuthNoPriv | authNoPriv | authPriv
auth_protocol:  MD5 | SHA | SHA224 | SHA256 | SHA384 | SHA512
priv_protocol:  DES | AES | AES192 | AES192C | AES256 | AES256C
```

The exporter also accepts `context_name`; the contract does not use it.

**Where the secret lives:** the device file stores the profile NAME only; the credentials live solely in `snmp_auths.yaml`, whose value the implementation hides as a secret (section [9](#9-secret-contract)), and never in labels or in the device list. This reinforces [13.1](#131-must-not-be-stored-in-docker-labels) (SNMP communities are forbidden in labels); section [9](#9-secret-contract) treats it as an exception to the "one file per `<auth-id>`" convention. Relabel checks only the PRESENCE of `auth` (`keep auth != ""`): no name format is imposed.

**Known limitation:** `merge` preserves the built-in defaults, including the insecure `public_v2` (community `public`, v2c) and `public_v1` (`version: 1`, outside the `{2, 3}` allowlist); `auth: "public_v2"` resolves successfully because relabel checks presence rather than membership. Control by name is impossible in the reference (auth names depend on the deployment) -- a documented risk, like the one-sided module gate.

**An unknown auth name** (a typo, absent from the merged `auths:`) leads to an exporter-side error during the scrape rather than to a drop at discovery time (relabel cannot consult the secret file). Documented; no separate e2e is added.

### 10.7. Domain: ipmi

BMC/IPMI monitoring through an external `ipmi_exporter` (or another adapter). ipmi is not a mechanism of its own but a **special case of the [metrics](#101-domain-metrics) domain**: an external exporter polls the BMC over IPMI and publishes a Prometheus endpoint, and the collector scrapes that endpoint as an ordinary metrics target. The contract requires no IPMI-specific configuration in the collector.

#### 10.7.1. Labels

```text
ru.3ops.discovery.ipmi.enabled
ru.3ops.discovery.ipmi.address
ru.3ops.discovery.ipmi.module
ru.3ops.discovery.ipmi.secret-id
ru.3ops.discovery.ipmi.profile
```

The labels describe the intent (the BMC address, the exporter module, the secret, the profile), but the role of the collector comes down to scraping the HTTP endpoint of an external exporter: there is no domain pipeline in the collector as there is for snmp ([10.6](#106-domain-snmp)). Every ipmi label in `0.2` is declarative/inventory (no implementation and no domain pipeline reads them); `ipmi.profile` refers to the scrape profiles of section [8.2](#82-scrape-profiles): ipmi has no profile family of its own. The secret file is `/run/alloy-secrets/<secret-id>.ipmi` per the shared contract of section [9](#9-secret-contract); the BMC credentials are consumed by the exporter itself, not by the collector.

The recommended path is to mark the `ipmi_exporter` container with the labels of the [metrics](#101-domain-metrics) domain and scrape it through the collector's metrics pipeline.

## 11. Validation rules

The minimal checks before a pipeline is created:

- `enabled == true` -- except for the logs domain (see section [10.3.1](#1031-default-collection-policy)); for the otel and ipmi domains the check does not apply: their labels are declarative and no pipeline is created from them (section [5](#5-global-labels));
- `version` is supported (in `0.2` the check is reserved -- see section [5](#5-global-labels));
- `domain.enabled == true`;
- `type` belongs to the allowlist;
- `port` is a number in 1..65535;
- `profile` belongs to the profile allowlist of the domain (section [8](#8-profiles)) -- except for the logs domain, where an unknown profile does not drop the container but results in `raw-v1` (section [10.3.4](#1034-unknown-profile));
- `secret-id` matches the allowlist regex;
- `path` starts with `/`;
- `scheme` belongs to the allowlist.

An unknown `type` value drops the target entirely (fail-closed) and is reflected in the collector's own log where possible.

An empty value of any label is equivalent to the label being absent: the default of the corresponding domain applies, and empty values never reach the series.

A mandatory label has no default, so for those the same rule means dropping: an empty mandatory label = an absent mandatory label = the target is dropped (fail-closed). This is a consequence rather than a special case: an implementation must check the presence of a non-empty value separately, because comparing an empty declared port against an empty port from the container metadata succeeds and lets the target through. The presence check is mandatory for `metrics.port`, `metrics.job` and `blackbox.port`.

The `port` check is fail-closed, by matching the declared port against the real private ports of the container: a non-numeric, out-of-range or non-existent value drops the target.

The snmp file provider checks its counterparts fail-closed in the same way: an entry with a `module` outside the allowlist, without `auth` or without `address` is dropped row by row, while the other entries of the file keep being collected. Matching `port` against container ports does not apply (there is no container). A syntactically broken device file as a whole is a different failure mode, not a row-by-row one: the row-by-row check does not apply to it, and its behaviour is set by the implementation.

## 12. Lifecycle

### 12.1. Adding a target

1. The container starts with `ru.3ops.discovery.enabled=true` (the logs domain is the exception: collection is on by default, section [10.3.1](#1031-default-collection-policy)).
2. The implementation discovers the container and checks the domain labels (section [11](#11-validation-rules)); a container that fails the check does not become a target.
3. The target appears: the implementation starts scraping the metrics or reading the logs of the container.
4. Metrics or logs start reaching the store.

Up to one `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` interval passes from the container start to the appearance of the target (section [14.1](#141-environment-parameters)); the first metric series arrive after the first scrape of the target at the interval of its profile (section [8.2](#82-scrape-profiles)).

### 12.2. Removing a target

1. The container is stopped or removed.
2. The target disappears: the implementation stops collecting it within one `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` interval.
3. New data stops arriving.
4. Historical data stays in the store until retention expires.

### 12.3. Changing labels

Docker does not allow changing the labels of a running container. Changes take effect only after the container is recreated with the new labels.

## 13. Security requirements

The collector's own logs are sensitive data. The implementation writes configuration-load diagnostics into them, and those may contain fragments of the values it read, hidden ones included (the limits of hiding are in section [9](#9-secret-contract)). By default the logs domain collects the stdout/stderr of every container, the collector's own container included (section [10.3.1](#1031-default-collection-policy)): a deliberate choice in favour of observing the collector, not an oversight. If the log store is trusted less than the secret directory, collection for the collector is switched off with an explicit `ru.3ops.discovery.logs.enabled=false` on its container.

### 13.1. Must not be stored in Docker labels

```text
passwords
API tokens
full DSNs
TLS private keys
SSH keys
SNMP communities
JWT
cookie/session values
```

### 13.2. May be stored

```text
secret-id
the name of an auth profile (snmp)
the name of the monitoring user
the database name
the port
the protocol
job
instance
environment
team
the profile name (scrape/log/database)
the metrics path
```

### 13.3. Docker socket

An implementation uses the Docker API read-only: it discovers containers and reads their metadata and logs. It gets the logs and metadata of containers through the Docker API alone; reading the files of `/var/lib/docker` is forbidden. Access to the Docker API must take the following into account:

- a read-only mount of `/var/run/docker.sock` does not make the Docker API strictly read-only;
- access to the Docker socket is effectively highly privileged;
- a socket proxy allowing read endpoints only is recommended;
- the collector UI must not be published outward without authentication.

A socket proxy narrows the privilege without removing it. The proxy allowlist works by API section rather than by individual path: permitting `/containers` permits EVERY GET in that section, including `/containers/{id}/json` (the container's environment variables, meaning passwords passed through `environment`), `/containers/{id}/archive?path=/` (reading an arbitrary file out of any container) and `/containers/{id}/export`. Discovery cannot work otherwise: container logs are read through the same section. What follows in practice: a collector with access to the proxy is equivalent to a reader of every container's secrets on that host, and the proxy belongs on an internal network unreachable by the workloads: it lowers the risk of the daemon being compromised, not the risk of someone else's data being read.

The requirement "the collector must not be reachable from an untrusted Docker network" cannot be met in full, and that is a property of the model rather than an oversight in the configuration. Scraping a container means sharing a network with it, so a collector is always a neighbour of what it collects from: the collector's HTTP server (its metrics and UI) and the opt-in OTLP receiver are visible to every container on that network. Splitting networks does not help: to scrape a container, the collector has to sit in its network. What follows in practice: untrusted workloads are separated by a collector of their own, not by a network of the same one; on a shared network, assume neighbours can reach the collector UI, and with it the configuration it shows (hidden values in it are replaced by the marker, section [9](#9-secret-contract)).

### 13.4. Secret path traversal

`secret-id` must be validated before the path is built (see section [9](#9-secret-contract)).

A bad example:

```text
../../etc/shadow
```

A good example:

```text
postgres-orders
```

### 13.5. Trust in labels

Labels are declared by the container itself, so the right to start containers on the host means the right to declare any values of `job`, `instance`, `team`, `environment`, `service_name`, `compose_project` and `compose_service` -- including someone else's. The boundaries of that trust:

- for the metrics and database domains SSRF is excluded by two conditions at once, and the second is as mandatory as the first. The scrape address is built only from the IP address of the container itself in its Docker network and from its private port (for database, from the secret file, which labels do not choose beyond `secret-id`), so labels cannot redirect collection to another host. The scrape response is an untrusted input too: a container answering `302` with a link-local address would send the next request there on the collector's behalf. The implementation therefore does not follow HTTP redirects when scraping; an implementation that follows them does not carry the guarantee;
- the blackbox domain is a deliberate exception: `blackbox.address` (section [10.4.1](#1041-labels)) points a probe at an arbitrary host, and the result (`probe_success`, the status, the certificate expiry) is visible in the metrics: the container gains a network reachability oracle acting as the collector. The probe port is limited to the private ports of the container itself, but the container declares its own exposed ports, so with untrusted neighbours `blackbox.address` should be constrained by an allowlist rule;
- the opt-in OTLP receiver of the otel domain listens without authentication and produces no provenance labels (section [10.5](#105-domain-otel)): network access to its ports equals the right to write telemetry with an arbitrary identity; the receiver should be kept on an internal network or fronted by an authenticating reverse proxy;
- `container` is added from the Docker engine metadata and `host` from the deployment parameter `RU_3OPS_DISCOVERY_HOSTNAME`, which defaults to the collector hostname; labels set neither of them (section [6.1](#61-labels-added-by-the-implementation));
- consequently, series and log streams with forged `job`/`team`/`service_name` still carry the honest `container` and `host` of the sender: they do not merge with the data of the real owner and stay distinguishable, but alert rules and dashboards that filter by `team`/`job` alone without regard for `container` will see the forged data too;
- fields taken from log content are not promoted into indexed fields (section [6.2](#62-log-fields));
- with untrusted neighbours on the host, the values of `team`/`environment`/`service_name` should additionally be constrained by allowlist rules; the contract sets no such rules;
- the contract sets no limit on telemetry volume: a container can generate load through log volume and through the number of opt-in targets; the defence is rate limits on the backend side (Loki limits, remote_write endpoint limits).

## 14. Implementations

An implementation is an agent with its own configuration that fulfils the contract for one or more domains of section [10](#10-domains). The implementation name is the value of the `collector` label (section [6.1](#61-labels-added-by-the-implementation)).

| Implementation | Domains | Agent | Directory |
|---|---|---|---|
| `alloy` | `metrics`, `database`, `logs`, `blackbox`, `otel`, `snmp`, `ipmi`, `host-metrics`, `container-metrics`, `host-logs` | Grafana Alloy, version pinned in section [14.4](#144-reference-implementation-alloy) | [`alloy/`](../alloy/), [`alloy-optional/`](../alloy-optional/) |

The domains of one host may be split between implementations, but each domain on a host is served by exactly one collector. Two collectors of one domain (two different implementations or two instances of one) produce duplicate series and lines that the storage cannot tell from real data, so such a deployment is an error. The symptom of the error is series or log streams that differ only in `collector` or `host`, or two running collectors of one domain on a host; the second symptom is needed when the labels of the duplicates match entirely.

For each of its domains an implementation must:

- understand the labels and follow the behaviour of sections 3-11;
- produce the series of the series catalog (section [14.3](#143-series-catalog));
- meet the security requirements of section [13](#13-security-requirements);
- understand the environment parameters of section [14.1](#141-environment-parameters) that belong to its domains and outputs.

The divergences of the reference from the contract that the gates allow are listed with their reasons in one place: [`tests/static/asymmetries.py`](../tests/static/asymmetries.py).

### 14.1. Environment parameters

Deployment-specific values are set through environment variables; when a variable is unset, the default applies. An implementation must understand the parameters of its domains and outputs. The `RU_3OPS_DISCOVERY_` prefix stands for 3ops Discovery.

| Variable | Purpose | Default |
|---|---|---|
| `RU_3OPS_DISCOVERY_DOCKER_HOST` | The Docker daemon address | `unix:///var/run/docker.sock` |
| `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` | The target list refresh interval | `30s` |
| `RU_3OPS_DISCOVERY_HOSTNAME` | The value of the `host` label (section 6.1) | `collector hostname` |
| `RU_3OPS_DISCOVERY_SECRETS_DIR` | The directory of secret files (see [9](#9-secret-contract)) | `/run/alloy-secrets` |
| `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL` | The metrics endpoint (Prometheus remote_write protocol) | `http://prometheus:9090/api/v1/write` |
| `RU_3OPS_DISCOVERY_LOKI_PUSH_URL` | The logs endpoint (Loki push API) | `http://loki:3100/loki/api/v1/push` |
| `RU_3OPS_DISCOVERY_HOST_ROOTFS_PATH` | The mount point of the host root filesystem (the `host-metrics` domain) | `/rootfs` |
| `RU_3OPS_DISCOVERY_HOST_PROCFS_PATH` | The mount point of the host procfs (the `host-metrics` domain) | `/host/proc` |
| `RU_3OPS_DISCOVERY_HOST_SYSFS_PATH` | The mount point of the host sysfs (the `host-metrics` domain) | `/host/sys` |
| `RU_3OPS_DISCOVERY_SNMP_TARGETS_FILE` | The path to the snmp device file (not a secret; the `snmp` domain) | `/etc/alloy/snmp_targets.yaml` |

The scrape profile parameters (interval/timeout) are not configurable through environment variables: they are part of the contract (see [8.2](#82-scrape-profiles)), not deployment configuration.

### 14.2. Output protocols and stores

An implementation sends metrics over the Prometheus remote_write protocol to the `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL` address. Any store that accepts remote_write fits: Prometheus, Mimir, VictoriaMetrics, Thanos, Grafana Cloud.

For logs the contract fixes the result in the store rather than the protocol: the indexed and non-indexed fields of section [6.2](#62-log-fields) and the profile fields of section [8.3](#83-log-profiles). The implementation chooses the protocol (Loki push, the store's native ingestion, OTLP) and declares the stores it supports. Over Loki push the logs are accepted by both Loki and VictoriaLogs: in both cases the address is set by `RU_3OPS_DISCOVERY_LOKI_PUSH_URL`.

VictoriaLogs without the `-loki.disableMessageParsing` flag parses a JSON line received over Loki push into fields: the store gains fields beyond sections 6.2 and 8.3, and `_msg` no longer holds the original line. A deployment that needs exactly the contract fields runs VictoriaLogs with this flag.

Credentials are not embedded into URLs (`https://user:pass@host`): the value of a variable is an ordinary string and may show up in the collector's UI and logs. If the store requires authentication, the implementation takes the credentials from a secret file, not from the URL.

The contract sets no delivery guarantee stronger than at-least-once: a restart or recreation of the collector may resend log history and lose unsent metrics. Persisting the collector's state across recreations is the implementation's job.

### 14.3. Series catalog

The series catalog is a normative machine-readable appendix to the manifest: the names and labels of the series of every domain, identical across all implementations of that domain. It lives in [`docs/series/`](series/): one `<domain>.yaml` file per domain of the identity table in section [6.1](#61-labels-added-by-the-implementation).

```yaml
domain: database
cells:
  postgres/basic-v1:
    identity: [job, instance, host, collector, container, compose_project, compose_service]
    present: [up, pg_up, pg_stat_activity_count]
    absent: [pg_settings_max_connections]
```

A cell is a profile or a module of the domain: `scrape` in `metrics`, `<type>/<profile>` in `database`, the module name in `blackbox` and `snmp`, `node` in `host-metrics`, `cadvisor` in `container-metrics`. `present` lists the series an implementation must emit, `identity` the labels each of them must carry. `absent` lists the series the profile must switch off; the key is allowed only in the `database` domain, which is how section [8.4](#84-database-profiles) is expressed in series. An unknown key and an empty `present` are catalog load errors: a cell without required series would pass any check.

The catalog is a lower bound: series and labels beyond it are allowed. It pins only the names of series and labels, never their values. It does not catch a change of meaning under the same name: units and the series type (counter or gauge) are not part of it.

The catalog is snapshotted from the e2e stack of the reference implementation at the pinned version (section [14.4](#144-reference-implementation-alloy)) and reviewed by a maintainer. It is rebuilt on every change of the pinned version and on every exporter upgrade in a second implementation. A divergence between an implementation and the catalog is resolved either by editing the catalog - a contract change with a CHANGELOG entry - or by a row with a reason in [`tests/static/asymmetries.py`](../tests/static/asymmetries.py). The same file lists the type/profile pairs of the `database` domain the catalog does not carry: no e2e container runs them.

Logs have no series and no catalog of their own: the fields of their records are set by sections [6.2](#62-log-fields) and [8.3](#83-log-profiles).

### 14.4. Reference implementation: Alloy

The reference implementation is a Grafana Alloy configuration: the base files in the [`alloy/`](../alloy/) directory, the optional ones in [`alloy-optional/`](../alloy-optional/) (section [14.4.3](#1443-optional-files)). Every `*.alloy` file of the directory forms one configuration and they run together:

```sh
alloy run --stability.level=experimental alloy/
```

The `--stability.level=experimental` flag is required by the `foreach` block in file 030 (experimental in Alloy v1.21). A syntax check without running:

```sh
docker run --rm -v "$PWD/alloy:/etc/alloy:ro" grafana/alloy:v1.21.2 \
  validate --stability.level=experimental /etc/alloy
```

The Alloy version policy. The tag in the command above is normative: the contract has been verified on exactly that tag, and the same one must appear in `noxfile.ALLOY_IMAGE` (checked both ways by a static gate). The contract declares no range of compatible versions -- not because versions do not matter, but because exactly one has honestly been verified: updating the tag is a change to the contract and passes the same gates (`alloy fmt`, `validate` for every combination, e2e). No lower bound is given deliberately: `foreach` is experimental, and upstream guarantees neither syntax stability nor the continued existence of an experimental block in the next release.

The reference offers no configuration free of experimental features: `foreach` lives in the base file [`030_database.alloy`](../alloy/030_database.alloy), so `--stability.level=experimental` is mandatory for the whole reference rather than for the database domain alone. A deployment that cannot accept experimental features excludes file 030 entirely -- and with it the database domain; no other domain depends on `foreach`.

| File | Content |
|---|---|
| [`010_discovery.alloy`](../alloy/010_discovery.alloy) | `discovery.docker`: opt-in discovery for metrics/database and discovery of every container for logs |
| [`020_metrics.alloy`](../alloy/020_metrics.alloy) | The metrics domain: a shared relabel (validation plus provenance) and a `discovery.relabel`/`prometheus.scrape` pair per profile of section [8.2](#82-scrape-profiles) |
| [`030_database.alloy`](../alloy/030_database.alloy) | The database domain: a `foreach` pipeline per database type, the DSN from a secret file, the collection volume from `database.profile` (section [8.4](#84-database-profiles)) |
| [`035_blackbox.alloy`](../alloy/035_blackbox.alloy) | The blackbox domain: a shared `discovery.relabel` plus `prometheus.exporter.blackbox` (modules `http_2xx`/`tcp_connect`/`icmp`/`tls_connect`) and a filter-plus-scrape pair per profile of section [8.2](#82-scrape-profiles) |
| [`040_logs.alloy`](../alloy/040_logs.alloy) | The logs domain: relabel rules and `loki.source.docker` |
| [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy) | The profile dispatcher: `loki.process` with the base log profiles |
| [`090_outputs.alloy`](../alloy/090_outputs.alloy) | The outputs: `prometheus.remote_write` and `loki.write` |

The file order, the layout of the profile pairs, the per-port target fan-out, state storage and store integration are described in [`alloy/README.md`](../alloy/README.md).

#### 14.4.1. Customization

Alloy merges every `*.alloy` file of a directory into a single component graph (top level, non-recursively); component names are globally unique. A base component cannot be overridden: two declarations with the same name are a load error, not an override. Customization is done in three ways:

- **an overlay directory** -- extra files added to the base directory at materialization time (section [14.4.3](#1443-optional-files)); the base `alloy/` stays valid and complete without them;
- **extension points** -- stable exports of the base that an overlay may reference (section [14.4.2](#1442-extension-points));
- **env parameterization** -- deployment values through `RU_3OPS_DISCOVERY_*` (section [14.1](#141-environment-parameters)).

Conventions against collisions: repository files use the numeric prefixes `0xx`, user overlays use `1xx` and above; user component names use the `ext_` prefix. The base/optional boundary criterion: the base `alloy/` contains exactly what is driven by discovery through Docker labels, while anything static, host-level or requiring deployment privileges is moved into optional.

Privileged overlays receive host-level deployment privileges and observe the host or all of its containers as a whole, outside the discovery scope: [`070_host-metrics`](../alloy-optional/070_host-metrics.alloy) (host procfs/sysfs/rootfs), [`080_host-logs`](../alloy-optional/080_host-logs.alloy) (systemd journal), [`075_container-metrics`](../alloy-optional/075_container-metrics.alloy) (the host cgroup namespace plus `/sys/fs/cgroup:ro`; the host PID namespace is neither required nor granted). Granting such privileges is a deliberate deployment decision, not a default. "Host-level privileges" means something specific: `070` mounts the host filesystem root (`/:/rootfs:ro`) for the sake of `node_filesystem_*`, and that is read access to EVERYTHING -- `/etc/shadow`, private SSH keys, the `/var/lib/docker` layers along with the contents of every other container. Mounting less is not an option: filesystem metrics require seeing the mount points. The only thing the reference masks separately is the Docker socket (`/dev/null` over `/rootfs/var/run/docker.sock`), so that a read privilege does not become a privilege to drive the daemon; everything else is read-only and available. `080` grants the system journal, `075` the statistics of every container on the host, including ones outside discovery.

#### 14.4.2. Extension points

The public API of the base configuration: the stable exports an overlay file may reference. They are stable within a minor version of the contract; renaming one is a breaking change.

| Export | Component |
|---|---|
| `prometheus.remote_write.default.receiver` | [`090_outputs.alloy`](../alloy/090_outputs.alloy) |
| `loki.write.default.receiver` | [`090_outputs.alloy`](../alloy/090_outputs.alloy) |
| `loki.process.docker_profiles.receiver` | [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy) |
| `discovery.docker.containers.targets` | [`010_discovery.alloy`](../alloy/010_discovery.alloy) |
| `discovery.docker.docker_logs.targets` | [`010_discovery.alloy`](../alloy/010_discovery.alloy) |

#### 14.4.3. Optional files

The [`alloy-optional/`](../alloy-optional/) directory holds overlay files added to the base directory at materialization time. The base `alloy/` is valid without them.

| File | Content |
|---|---|
| [`060_otel.alloy`](../alloy-optional/060_otel.alloy) | Opt-in OTLP receiver: `otelcol.receiver.otlp`, with metrics going to `prometheus.remote_write` and logs to `loki.write` through an allowlist processor |
| [`070_host-metrics.alloy`](../alloy-optional/070_host-metrics.alloy) | Opt-in host metrics: `prometheus.exporter.unix` (`node_*` series) into `prometheus.remote_write`; rootfs/procfs/sysfs through `RU_3OPS_DISCOVERY_HOST_*`; provenance per [6.1](#61-labels-added-by-the-implementation): `host`/`collector` are added by `discovery.relabel` before the scrape |
| [`075_container-metrics.alloy`](../alloy-optional/075_container-metrics.alloy) | Opt-in per-container metrics: `prometheus.exporter.cadvisor` (series `container_cpu_*`/`container_memory_*`/`container_network_*`; `container_fs_*` is outside the perimeter) into `prometheus.remote_write`. The Docker API goes through `docker_host` (reusing `RU_3OPS_DISCOVERY_DOCKER_HOST`, socket proxy: a GET allowlist of the `CONTAINERS`/`INFO`/`VERSION`/`PING` sections is enough); with the Docker API unavailable the output is practically empty (`docker_only`). Provenance per [6.1](#61-labels-added-by-the-implementation): allowlisted container labels become `environment`/`team`/`compose_*`, `name` becomes `container`; raw `container_label_*`/`id`/`name` are dropped; `instance` is the collector hostname and `job` is `integrations/cadvisor` (the exporter's own label; both are deliberate gaps). Cardinality: `store_container_labels = false` plus the allowlist, root cgroup statistics disabled, `disabled_metrics`/`enabled_metrics` tunable. Deployment privileges (the host cgroup namespace) are covered in section [14.4.1](#1441-customization); per-container opt-out is not supported. |
| [`080_host-logs.alloy`](../alloy-optional/080_host-logs.alloy) | Opt-in host logs: `loki.source.journal` (systemd journal) into `loki.write`; the static labels `host`/`collector`/`source` (allowlisted in [6.2](#62-log-fields)) |
| [`037_snmp.alloy`](../alloy-optional/037_snmp.alloy) | The snmp domain (opt-in overlay): the file provider (`local.file` plus `encoding.from_yaml`), `prometheus.exporter.snmp` (modules `if_mib`/`system`, profile `snmp-standard-v1`), auth from an inline `config` secret (`local.file` with `is_secret`) through merge. Enabled only together with the device and auth files (a top-level `local.file` without a file is unhealthy). |

#### 14.4.4. How the reference fulfils the contract

The contract sections state their requirements without naming an implementation. This list collects, section by section, how Alloy fulfils them; it adds no requirement of its own.

- [§2](#2-base-model): the component graph of the reference is Docker labels -> `discovery.docker` -> `discovery.relabel` -> `foreach` / `prometheus.scrape` / `loki.source.docker` -> `prometheus.remote_write` / `loki.write`.
- [§4](#4-label-key-normalization): `discovery.docker` hands a container label over as `__meta_docker_container_label_<name>`, replacing dots, hyphens and other unsuitable characters in the name with `_`; the configuration reads the label `ru.3ops.discovery.database.secret-id` as `__meta_docker_container_label_ru_3ops_discovery_database_secret_id`.
- [§5](#5-global-labels): the reference does not read the `ru.3ops.discovery.version` label and processes every container by the `0.2` rules.
- [§6.1](#61-labels-added-by-the-implementation): `collector` equals `alloy`; every file that produces series or streams, except [`060_otel.alloy`](../alloy-optional/060_otel.alloy), computes `host` as `coalesce(sys.env("RU_3OPS_DISCOVERY_HOSTNAME"), constants.hostname)`, so an unset or empty parameter yields the hostname of the Alloy container. The OTLP path is an exemption from provenance (section [10.5](#105-domain-otel)): its series and streams carry neither `host` nor `collector`.
- [§6.2](#62-log-fields): logs leave through `loki.write` over the Loki push API, to Loki and to VictoriaLogs alike; indexed fields become stream labels, non-indexed ones structured metadata (`stage.structured_metadata` in [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy)). The reference does not promote `level` into stream labels and does not truncate structured metadata values.
- [§8.1](#81-general-rules): the names of profile components are derived from the profile name mechanically ([`alloy/README.md`](../alloy/README.md#layered-profile-pairs)), hence the `[a-z0-9-]` alphabet.
- [§8.2](#82-scrape-profiles): a single `prometheus.scrape` has one `scrape_interval` and one `scrape_timeout`, so every profile gets its own `discovery.relabel`/`prometheus.scrape` pair ([`020_metrics.alloy`](../alloy/020_metrics.alloy)); no scrape component is created for a user-supplied value.
- [§8.4](#84-database-profiles): profiles map onto exporter collectors ([`030_database.alloy`](../alloy/030_database.alloy)):
  - `postgres`: `basic-v1` - the exporter defaults without `pg_settings` (`disable_settings_metrics`); `standard-v1` - the exporter defaults; `extended-v1` - `enabled_collectors` made of the 11 collectors enabled by default in the pinned exporter fork (`database`, `locks`, `replication`, `replication_slot`, `roles`, `stat_bgwriter`, `stat_database`, `stat_progress_vacuum`, `stat_user_tables`, `statio_user_tables`, `wal`) and four extras (`database_wraparound`, `long_running_transactions`, `process_idle`, `statio_user_indexes`): a non-empty list replaces the default set rather than adding to it.
  - `mysql`/`mariadb`: `basic-v1` - `global_status`, `global_variables`; `standard-v1` - the six default collectors, pinned explicitly in `set_collectors`; `extended-v1` - the same plus `engine_innodb_status`, `info_schema.processlist`, `auto_increment.columns`.
  - `redis`: `basic-v1` - `redis_metrics_only`; in the pinned version the flag only removes `redis_exporter_build_info` from the exporter's internal registry, which Alloy does not serve, and Alloy produces no series outside `redis_*` without it either (`include_exporter_metrics = false`), so in series `basic-v1` equals `standard-v1`; `standard-v1` - the exporter defaults; `extended-v1` - the defaults plus `export_client_list` and `incl_system_metrics`.
  - `mongodb`: `basic-v1` - diagnostic data only (`serverStatus`, `enable_diagnostic_data`); `standard-v1` and `extended-v1` - `collect_all` plus explicit `enable_*` flags equal to the ones `collect_all` turns on: without them the first scrape of each exporter is incomplete. `extended-v1` equals `standard-v1` because the mongodb exporter default is already maximal.
- [§9](#9-secret-contract): a secret file is read by `local.file` at `coalesce(sys.env("RU_3OPS_DISCOVERY_SECRETS_DIR"), "/run/alloy-secrets")` + `/<secret-id>.<suffix>`; hiding comes from `is_secret = true`, and the Alloy API and component exports hand the value out as `(secret)`. The address-only redis `.dsn` is read with `is_secret = false`: the exporter's `redis_addr` argument takes a plain string rather than a secret; the password from `.redispass` goes through `redis_password`.
- [§9](#9-secret-contract), the hiding limit: when the declared type and the file content disagree, the Alloy configuration-load error message may quote a fragment of the value read. This is Alloy behaviour, and no configuration changes it.
- [§9](#9-secret-contract), the failure radius: in the database domain a missing secret file takes down the WHOLE `foreach` block of its database type. A container declaring a regex-valid `secret-id` with no file behind it fails the evaluation of the entire block, and legitimate databases OF THE SAME TYPE stop being collected with it; databases of other types live in their own blocks and are untouched. The failure is reversible: once the container is removed, the block recovers on its own. The reading "a `local.file` per iteration, therefore a per-iteration failure" is wrong: that is established by reproduction rather than derived from how `foreach` is built. The separation by type is a side effect of the configuration's structure, not a protection; the health of Alloy components needs monitoring. A top-level `local.file` (the snmp file provider, section [10.6](#106-domain-snmp)) has no localization at all: its path is set by the operator, and a missing file brings the graph down in a cascade, so overlay 037 is loaded only together with its files.
- [§10.2](#102-domain-database): each type is served by an Alloy exporter: `prometheus.exporter.postgres`, `prometheus.exporter.mysql` (also for `mariadb`), `prometheus.exporter.redis`, `prometheus.exporter.mongodb`. The port is matched by a `keepequal` rule against `__meta_docker_port_private`; the reference does not detect a mismatch between the port in the label and in the DSN.
- [§10.3.1](#1031-default-collection-policy): the reference excludes the container before the source: `discovery.relabel` drops a target with `logs.enabled=false`, and `loki.source.docker` never opens the stream of that container. The chain: `discovery.docker` (every container) -> `discovery.relabel` (excludes `logs.enabled=false` only) -> `loki.source.docker` -> `loki.process` (the profile dispatcher) -> `loki.write`.
- [§10.3.4](#1034-unknown-profile): the reference fulfils items 1-2 with an allowlist rule in `discovery.relabel` that replaces an unknown profile with `raw-v1`. The reference does not fulfil items 3-4: the diagnostic message and the metric are unavailable at the relabel level.
- [§10.4](#104-domain-blackbox): the module allowlist is `http_2xx`, `tcp_connect`, `icmp`, `tls_connect`; it is set by a `discovery.relabel` keep rule and by the inline `config` of the `prometheus.exporter.blackbox` component ([`035_blackbox.alloy`](../alloy/035_blackbox.alloy)).
- [§10.5](#105-domain-otel): the receiver is `otelcol.receiver.otlp` in the overlay [`060_otel.alloy`](../alloy-optional/060_otel.alloy); a different port is an edit of that overlay, a customization under section [14.4.1](#1441-customization).
- [§10.6](#106-domain-snmp): the domain ships as the overlay file [`037_snmp.alloy`](../alloy-optional/037_snmp.alloy) (section [14.4.3](#1443-optional-files)) rather than as a base file: its top-level `local.file` becomes unhealthy without a file on disk and brings the graph down in a cascade, so the overlay is loaded only together with the device file and the auth profile file. `encoding.from_yaml` decodes the device file into `list(map(string))`.
- [§10.6.1](#1061-snmp-auth): `snmp_auths.yaml` is fed to `prometheus.exporter.snmp` as an inline `config` from a `local.file` with `is_secret = true` and merged (`merge`) with the exporter's built-in auth profiles; the Alloy configuration does not inspect the file content.
- [§10.7](#107-domain-ipmi): Alloy has no native IPMI component, unlike snmp with its built-in `prometheus.exporter.snmp`, so the reference ships no ipmi overlay. A dedicated overlay will appear only if Alloy gains a native IPMI component.
- [§11](#11-validation-rules): the `path`, `scheme`, `profile` and `secret-id` checks are `discovery.relabel` rules; relabel removes a label with an empty value. The `port` check is implicit: `keepequal` matches the declared port against `__meta_docker_port_private`. Comparing two empty strings succeeds, so the presence of `metrics.port`, `metrics.job` and `blackbox.port` is checked by explicit keep rules with the regular expression `(.+)`. The snmp file provider ([`037_snmp.alloy`](../alloy-optional/037_snmp.alloy)) checks `module`, `auth` and `address` with `discovery.relabel` keep rules on top of the list from `encoding.from_yaml`. A syntactically broken device file as a whole breaks `from_yaml`, and Alloy holds on to the last valid arguments: the targets do not change (the **fail-STALE** mode, neither fail-closed nor an empty list). On a cold start there is no last valid value, so `discovery.relabel` is unhealthy and the target set is empty (the exporter starts with zero devices, healthy-idle). The row-by-row drop (semantics) and the whole-file fail-STALE (syntax) are two different modes.
- [§12](#12-lifecycle): `discovery.docker` discovers the container, `discovery.relabel` checks the domain labels, and for the database domain `foreach` builds a pipeline; the target is visible in the Alloy UI. When the container is removed, the `foreach` pipeline of the database domain is removed, while the static scrape components of the other domains simply lose the target.
- [§13.3](#133-docker-socket): the Docker API is used by `discovery.docker` and `loki.source.docker`; `loki.source.docker` reads logs through the `/containers` section. The Alloy HTTP server serves `/metrics` and the unauthenticated `/api/v0/web/components` with the component list and their arguments; values marked `is_secret` are replaced there by the `(secret)` marker. With several container networks `discovery.docker` takes only the alphabetically first one ([`alloy/README.md`](../alloy/README.md#per-port-fan-out-and-multiple-networks)).
- [§13.5](#135-trust-in-labels): the reference builds the scrape address from `__meta_docker_network_ip` and `__meta_docker_port_private`. `prometheus.scrape` follows redirects by default, so every `prometheus.scrape` of the reference sets `follow_redirects = false`. The reference contains no allowlist rules for `blackbox.address`, `team`, `environment` and `service_name`; with untrusted neighbours they are added to the `discovery.relabel` of the corresponding domain. The OTLP receiver is the overlay [`060_otel.alloy`](../alloy-optional/060_otel.alloy).

## 15. Usage

### 15.1. Docker Compose anchors

YAML anchors may be used to reduce duplication:

```yaml
x-3ops-discovery-common: &alloy-discovery-common
  ru.3ops.discovery.enabled: "true"
  ru.3ops.discovery.version: "0.2"
  ru.3ops.discovery.environment: "production"

services:
  rabbitmq:
    image: rabbitmq:4-management
    labels:
      <<: *alloy-discovery-common
      ru.3ops.discovery.instance: "rabbitmq-main"
      ru.3ops.discovery.team: "platform"

      ru.3ops.discovery.metrics.enabled: "true"
      ru.3ops.discovery.metrics.type: "prometheus"
      ru.3ops.discovery.metrics.port: "15692"
      ru.3ops.discovery.metrics.path: "/metrics"
      ru.3ops.discovery.metrics.job: "rabbitmq"

  postgres:
    image: postgres:18
    labels:
      <<: *alloy-discovery-common
      ru.3ops.discovery.instance: "orders-postgres"
      ru.3ops.discovery.team: "orders"

      ru.3ops.discovery.database.enabled: "true"
      ru.3ops.discovery.database.type: "postgres"
      ru.3ops.discovery.database.port: "5432"
      ru.3ops.discovery.database.secret-id: "postgres-orders"
```

The `x-` prefix in the name of the anchor key is mandatory and does NOT
contradict the reverse-DNS requirement for the labels themselves -- the
rule applies in two places in opposite directions:

- **A top-level key of a compose file** must be either a known key of the
  schema (`services`, `networks`, `volumes`, ...) or an extension key
  carrying the `x-` prefix. The key `ru.3ops.discovery-common` is neither,
  and `docker compose config` rejects such a file outright
  (`additional properties ... not allowed`).
- **A key inside `labels:`** must stay reverse-DNS (`ru.3ops.*`): in the
  map form of `labels:` compose treats a key with the `x-` prefix as an
  extension and never delivers it to the container under its own name --
  all such keys are folded into a single service label `#extensions` whose
  value looks like `map[x-key:value]`. Discovery does not see that label,
  and the container is left with a garbage one. This is exactly why the
  namespace of the contract is reverse-DNS rather than an `x-` prefix
  (section [4](#4-label-key-normalization)).

The anchor key is visible only to the YAML parser and reaches no container
at all -- its name is free apart from the mandatory `x-`.

### 15.2. Minimal contract summary

For a native Prometheus endpoint:

```yaml
labels:
  ru.3ops.discovery.enabled: "true"
  ru.3ops.discovery.version: "0.2"
  ru.3ops.discovery.instance: "rabbitmq-main"

  ru.3ops.discovery.metrics.enabled: "true"
  ru.3ops.discovery.metrics.type: "prometheus"
  ru.3ops.discovery.metrics.port: "15692"
  ru.3ops.discovery.metrics.path: "/metrics"
  ru.3ops.discovery.metrics.job: "rabbitmq"
```

For PostgreSQL:

```yaml
labels:
  ru.3ops.discovery.enabled: "true"
  ru.3ops.discovery.version: "0.2"
  ru.3ops.discovery.instance: "orders-postgres"

  ru.3ops.discovery.database.enabled: "true"
  ru.3ops.discovery.database.type: "postgres"
  ru.3ops.discovery.database.port: "5432"
  ru.3ops.discovery.database.secret-id: "postgres-orders"
```

For logs:

```yaml
labels:
  ru.3ops.discovery.version: "0.2"

  ru.3ops.discovery.logs.profile: "generic-logfmt-v1"
  ru.3ops.discovery.logs.service: "orders-api"
```

Without any labels a container is still collected as `raw-v1`.

To disable explicitly:

```yaml
labels:
  ru.3ops.discovery.logs.enabled: "false"
```

## 16. Out of scope

Version `0.2` does not describe:

- automatic creation of monitoring users in the databases;
- automatic secret rotation;
- a full-blown policy engine;
- automatic assignment of Grafana dashboards;
- dynamic creation of alert rules;
- Kubernetes annotations;
- dynamic construction of a log pipeline from a list of stages in a label;
- binding `secret-id` to a container identity (section [9](#9-secret-contract));
- multi-host global service discovery;
- a service ownership registry;
- a CMDB or an inventory source of truth.

These capabilities may be added by separate specifications.
