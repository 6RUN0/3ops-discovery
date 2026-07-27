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

`3ops Discovery` is a declarative mini-framework for automatic discovery and configuration of telemetry targets in Grafana Alloy, driven by Docker labels.

A container describes:

- which signals should be collected;
- which integration/exporter type to use;
- where to take the metrics or logs from;
- how to name the target;
- where Alloy should look for secrets;
- which extra labels to attach to the telemetry.

Alloy:

1. discovers containers through the Docker API;
2. filters targets by labels;
3. normalizes the metadata;
4. builds the scrape/exporter/logging pipeline;
5. sends metrics to Prometheus/VictoriaMetrics/Mimir;
6. sends logs to Loki;
7. never receives secrets directly from Docker labels.

## 2. Base model

```text
Docker labels
    ↓
discovery.docker
    ↓
discovery.relabel
    ↓
foreach / prometheus.scrape / loki.source.docker
    ↓
prometheus.remote_write / loki.write
```

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

## 4. Docker label normalization in Alloy

The Docker label:

```text
ru.3ops.discovery.database.secret-id
```

appears in `discovery.docker` as:

```text
__meta_docker_container_label_ru_3ops_discovery_database_secret_id
```

Dots, hyphens and other unsuitable characters are converted into `_`.

Because of that, the following labels collide after normalization:

```text
ru.3ops.discovery.database.secret-id
ru.3ops.discovery.database.secret.id
```

Only the first spelling may be used.

## 5. Global labels

### `ru.3ops.discovery.enabled`

The mandatory flag that opts a container into discovery for the metrics, database, blackbox, otel and ipmi domains.

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

If the label is absent, the contract version configured as the default by the Alloy configuration applies.

In version `0.2` the label is reserved: the reference configuration does not read it and processes every container by the `0.2` rules. Version validation will arrive together with the first change that alters label semantics (section [7](#7-contract-versioning)).

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

### 6.1. Labels added by Alloy

Alloy must add the following labels to metrics and logs whenever they are available:

```text
instance
environment
team
container
compose_project
compose_service
host
collector="alloy"
```

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

The `container` label comes from the Docker engine metadata and `host` from the hostname of the Alloy collector; neither is set by container labels, so a container cannot forge their values. The remaining labels are declared by the container itself (see section [13.5](#135-trust-in-labels)). For logs the set is additionally constrained by the allowlist of section [6.2](#62-loki-label-cardinality).

The `instance` label belongs to metrics; for logs its counterpart is `service_name` (see section [10.3.5](#1035-labels)).

### 6.2. Loki label cardinality

Only low-cardinality fields may be placed into Loki labels:

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

Stream labels are built solely from discovery metadata and container labels. Fields extracted from the content of a line are never promoted into stream labels: the content is under the control of the application, and such promotion opens the door to label spoofing and unbounded stream cardinality. The reference does not promote `level` (it is absent from the allowlist above and stays in the list below); a customization may promote `level` only if it normalizes the value to a bounded set and extends the allowlist.

The following fields must stay inside the line or in structured metadata:

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

For filtering by level, Loki 3.x computes `detected_level` on its own from the line content and structured metadata.

Structured metadata is neither indexed nor cardinality-bearing, but the size of the values is controlled by the application. Size is bounded by Loki limits (`max_structured_metadata_size`); the reference configuration does not truncate values.

Structured metadata requires Loki 3.x with schema v13 (TSDB) and `allow_structured_metadata` enabled. On an older schema the push is rejected as a whole: profiles that parse silently stop delivering lines while `raw-v1` keeps working -- on partial log loss this is the first thing worth checking.

## 7. Contract versioning

The contract version is carried by:

```yaml
ru.3ops.discovery.version: "0.2"
```

Rules:

- patch changes do not alter the meaning of existing labels;
- minor changes may add new optional labels;
- major changes may alter semantics or remove fields;
- starting from the first change that alters label semantics, the Alloy configuration must state the supported versions explicitly (in `0.2` the check is reserved, see section [5](#5-global-labels)).

The label carries the major and minor parts only: patch changes by definition do not alter label semantics and are not reflected in the contract.

## 8. Profiles

### 8.1. General rules

A profile is the name of a predefined, versioned set of settings described in the Alloy configuration.

- The value of `*.profile` is picked only from the allowlist defined by the Alloy configuration.
- The label is neither a DSL nor a pipeline programming language: arbitrary values and stage lists are not supported.
- A profile name must carry a version: the suffix `-vN`, with the full name made of `[a-z0-9-]` (the names of profile components are derived from it mechanically, section [14](#14-reference-implementation)).
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

A single `prometheus.scrape` component has one `scrape_interval` and one `scrape_timeout`, so arbitrary interval/timeout values from labels are not supported.

A bounded set of versioned profiles is used instead: every profile gets its own `discovery.relabel`/`prometheus.scrape` pair (see [alloy/020_metrics.alloy](../alloy/020_metrics.alloy)). No arbitrary scrape component is created for a user-supplied value.

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

### 8.4. Database profiles

```text
basic-v1
standard-v1
extended-v1
```

The profiles make it possible to control the load without accepting arbitrary settings from labels. They are selected through `ru.3ops.discovery.database.profile`; the default is `standard-v1`.

A database profile governs the collection volume of the exporter -- which collectors query the database -- rather than the scrape cadence: the scrape profiles of section [8.2](#82-scrape-profiles) apply to the `metrics` and `blackbox` domains only. The load is monotonic: basic <= standard <= extended. `standard-v1` matches the default collector set of the exporter; an incompatible change of the set requires a new profile name (section [8.1](#81-general-rules)). A value outside the allowlist drops the target entirely (fail-closed), as in every other domain with profiles.

The mapping of profiles onto collectors in the reference configuration ([alloy/030_database.alloy](../alloy/030_database.alloy)); the extended sets only include collectors that work on a vanilla database without extensions or special server settings:

| Type | `basic-v1` | `standard-v1` | `extended-v1` |
|---|---|---|---|
| `postgres` | default metrics without `pg_settings` | exporter defaults | defaults plus `database_wraparound`, `long_running_transactions`, `process_idle`, `statio_user_indexes` |
| `mysql`/`mariadb` | `global_status`, `global_variables` | the six default collectors (pinned explicitly) | defaults plus `engine_innodb_status`, `info_schema.processlist`, `auto_increment.columns` |
| `redis` | `redis_*` series only (`redis_metrics_only`) | exporter defaults | defaults plus client list and system memory |
| `mongodb` | diagnostic data only (`serverStatus`) | full collection (`collect_all`) | equivalent to `standard-v1`: the mongodb exporter default is already maximal |

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

Alloy builds the path:

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

Redis is the exception: the exporter's `redis_addr` argument takes a plain string rather than a secret, so the address (`host:port`, non-secret) is stored in `.dsn` while the password goes into a separate secret file `<secret-id>.redispass` read through `redis_password`.

Requirements:

- the file is readable only by the Alloy user;
- the directory is mounted read-only;
- `local.file` with `is_secret = true` is used;
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

The identifier validation rules and the read-only mount are identical across domains; `is_secret = true` is mandatory for files with credentials (the exception is the address-only redis `.dsn`: it is non-secret by construction, see above, and is read without `is_secret`). The requirements for path traversal protection are described in section [13.4](#134-secret-path-traversal).

The `secret-id` space is a single trust domain within the host: the contract does not bind a container to a particular secret, and any container with a valid label may reference any existing secret file. Only secrets meant for the containers of that host should be placed into its secret directory; use a `secret-id` prefix convention to separate teams. Prefixes are an operator convention only: the configuration does not check them, and technically every secret file on the host is reachable by every container of that host. A consequence of the same trust model: a container can determine whether a secret file exists by declaring the corresponding `secret-id` and observing whether an exporter appears; the content of the secret is not disclosed. Binding `secret-id` to a container identity is out of scope for version `0.2` (section [16](#16-out-of-scope)).

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

`metrics.scheme: https` assumes a certificate the collector trusts through the system trust store: the label contract has no channel for delivering CA material (labels carry strings only -- the same model as the blackbox `tls_connect` module, section [10.4](#104-domain-blackbox)), so an endpoint with a self-signed certificate will not be scraped. TLS trust for internal CAs is an environment customization: a separate scrape pair with `tls_config` (section [14.3](#143-customizing-the-reference-configuration)).

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

The profile picks one of the relabel/scrape pairs of the Alloy configuration; the reference configuration ships pairs for every base profile of section [8.2](#82-scrape-profiles) (see section [14](#14-reference-implementation)).

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

Actual support depends on the presence of the corresponding `prometheus.exporter.*` in the Alloy version in use.

`type` denotes the wire protocol and the exporter, not the database vendor. Protocol-compatible builds are labeled with the base type and get no type of their own: Percona Server for MySQL and Percona XtraDB Cluster are `type: mysql`; Percona Server for MongoDB is `type: mongodb` (just like managed databases such as RDS/Aurora MySQL). MariaDB is the exception: it is a type in its own right that shares the mysql exporter, because operators perceive it as a separate product.

`database.port` (and the standard port in its absence) is a target selector rather than a connection parameter: the value is checked against the real private ports of the container (`keepequal`, fail-closed -- a target with a non-existent port is dropped), whereas the exporter connection address comes entirely from `.dsn` (section [9](#9-secret-contract)). A mismatch between the port in the label and in the DSN is not detected by the configuration.

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

For logs, `ru.3ops.discovery.enabled` is not a precondition. This is deliberate, so that a container without manifest labels is still visible in Loki.

The recommended chain:

```text
discovery.docker
    ↓ every container
discovery.relabel
    ↓ exclude logs.enabled=false only
loki.source.docker
    ↓
loki.process
    ↓ profile dispatcher
Loki
```

#### 10.3.2. `logs.profile`

`ru.3ops.discovery.logs.profile` is the name of a predefined pipeline profile from the allowlist (see sections [8.1](#81-general-rules) and [8.3](#83-log-profiles)).

Example:

```yaml
ru.3ops.discovery.logs.profile: "app-type-1-v1"
```

The value must not be an arbitrary list of stages: Alloy picks a profile only from the allowlist defined in the configuration.

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
3. write a diagnostic message into the Alloy log;
4. where possible, increment an internal discovery configuration error metric.

An unknown profile must never cause the loss of a container's logs.

The reference configuration implements items 1-2 with an allowlist rule in `discovery.relabel` (an unknown profile is replaced by `raw-v1`); the diagnostic message and the metric (items 3-4) are unavailable at the relabel level and are not implemented in the reference.

#### 10.3.5. Labels

| Label | Mandatory | Value |
|---|---:|---|
| `ru.3ops.discovery.logs.enabled` | No | Defaults to `true`; `false` disables collection |
| `ru.3ops.discovery.logs.profile` | No | Defaults to `raw-v1` |
| `ru.3ops.discovery.logs.service` | No | The `service_name` value |
| `ru.3ops.discovery.logs.stream-policy` | No | The stdout/stderr processing profile |
| `ru.3ops.discovery.logs.redaction-profile` | No | The identifier of the redaction policy |
| `ru.3ops.discovery.logs.drop-profile` | No | The identifier of the noise filtering policy |

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
| `ru.3ops.discovery.blackbox.address` | No | The probe address; defaults to the container address |
| `ru.3ops.discovery.blackbox.port` | Yes | The probe port |
| `ru.3ops.discovery.blackbox.path` | No | The HTTP path |
| `ru.3ops.discovery.blackbox.profile` | No | A scrape profile from the allowlist; defaults to `normal-v1` |

The `module` value must belong to the blackbox exporter module allowlist defined by the Alloy configuration. Arbitrary modules from labels are not accepted. The shape of the probe target depends on the module: HTTP modules receive the URL `scheme://host:port/path`, TCP and TLS modules receive `host:port`, ICMP modules receive the host alone. Alloy adds a `module` label carrying the name of the module used to every blackbox probe series.

For ICMP modules the `blackbox.port` value is not part of the probe itself (ICMP has no port), but the label stays mandatory and goes through the same validation: the declared port must match a real exposed port of the container, otherwise the target is dropped. The rule holds for an external `blackbox.address` too: the port is checked against the private ports of the container itself, so a probe of `example.com:443` from a container that does not expose port 443 is dropped silently. The consequences of `blackbox.address` for the trust model are covered in section [13.5](#135-trust-in-labels).

ICMP probes need no extra privileges in a typical Docker environment: the standard capability set (`NET_RAW`) or unprivileged ICMP sockets (Docker opens `net.ipv4.ping_group_range` for every group by default) is enough. In hardened environments where `NET_RAW` is dropped and `ping_group_range` is narrowed at the same time, ICMP probes will not work; the way out is to restore `cap_add: [NET_RAW]` or to widen `sysctls: net.ipv4.ping_group_range` on the Alloy container.

The reference TLS module (`tls_connect`) checks that the TLS handshake succeeds and reports certificate expiry metrics (`probe_ssl_earliest_cert_expiry`, `probe_tls_version_info`), but deliberately does not verify the trust chain: the label contract has no channel for delivering CA material into Alloy -- labels carry strings only. Chain verification for internal CAs is a property of a particular environment: it is done by a separate module with `ca_file` in the blackbox exporter configuration, which is outside the scope of the reference.

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

#### 10.5.1. Labels

| Label | Mandatory | Value |
|---|---:|---|
| `ru.3ops.discovery.otel.enabled` | Yes | `true` |
| `ru.3ops.discovery.otel.protocol` | Yes | `grpc` or `http` |
| `ru.3ops.discovery.otel.service` | No | The service name |
| `ru.3ops.discovery.otel.traces` | No | `true`/`false` |
| `ru.3ops.discovery.otel.metrics` | No | `true`/`false` |
| `ru.3ops.discovery.otel.logs` | No | `true`/`false` |

This domain mostly documents the expected behavior of the application. Alloy usually runs one shared OTLP receiver rather than a receiver per container.

The `otel.enabled` flag is therefore declarative: it does not govern OTLP ingestion (the receiver is shared and static) but records the intent of the service and serves inventory purposes. The remaining labels of the domain are declarative for the same reason. Traces are outside the perimeter in `0.2`: the reference receiver has no traces output, so a trace export is rejected with an explicit client-side error rather than accepted silently.

The OTLP path is an exception to the provenance of section [6.1](#61-labels-added-by-alloy): the shared receiver is static and has no Docker metadata, so it produces no `environment`/`team`/`container` provenance labels. Only an allowlisted set of OTLP resource attributes is promoted into the Loki stream (section [6.2](#62-loki-label-cardinality); in the reference configuration only `service.name` becomes `service_name`); the rest of the identification is supplied by the sending application itself through resource attributes.

### 10.6. Domain: snmp

The only domain not driven by Docker labels: external network equipment (switches, routers) has no container, so targets are enumerated in a file rather than discovered. The domain ships as the opt-in overlay file [`037_snmp.alloy`](../alloy-optional/037_snmp.alloy) (section [14.5](#145-optional-files)) rather than as a base domain: its top-level `local.file` becomes unhealthy without a file on disk and brings the whole graph down with it, so it is only loaded together with the device and auth files.

The device file (`snmp_targets.yaml`) is a list of entries; every value is stored as a string (`encoding.from_yaml` decodes the list into `list(map(string))`):

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

**Version allowlist:** SNMPv2c and SNMPv3. In the file the version is set by the `version` field as a NUMBER, not as the string `v2c`/`v3`: `version: 2` means v2c and `version: 3` means v3. The check is advisory only: the secret file is parsed by the exporter and the Alloy configuration never inspects it. The single control point in the repository is the static validator of the auth fixture (`tools/snmp_fixtures.py`, `validate_auths`): `version ∈ {2, 3}` (NOT the exporter range 1..3 -- SNMPv1 is forbidden by the contract).

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

**Where the secret lives:** the device file stores the profile NAME only; the credentials live solely in `snmp_auths.yaml`, supplied as an inline `config` from a `local.file` with `is_secret = true` -- never in labels and never in the device list. This reinforces [13.1](#131-must-not-be-stored-in-docker-labels) (SNMP communities are forbidden in labels); section [9](#9-secret-contract) treats it as an exception to the "one file per `<auth-id>`" convention. Relabel checks only the PRESENCE of `auth` (`keep auth != ""`) -- no name format is imposed.

**Known limitation:** `merge` preserves the built-in defaults, including the insecure `public_v2` (community `public`, v2c) and `public_v1` (`version: 1`, outside the `{2, 3}` allowlist); `auth: "public_v2"` resolves successfully because relabel checks presence rather than membership. Control by name is impossible in the reference (auth names depend on the deployment) -- a documented risk, like the one-sided module gate.

**An unknown auth name** (a typo, absent from the merged `auths:`) leads to an exporter-side error during the scrape rather than to a drop at discovery time (relabel cannot consult the secret file). Documented; no separate e2e is added.

### 10.7. Domain: ipmi

BMC/IPMI monitoring through an external `ipmi_exporter` (or another adapter). Alloy has no native IPMI component -- unlike snmp, where a built-in `prometheus.exporter.snmp` exists -- so ipmi is not a mechanism of its own but a **special case of the [metrics](#101-domain-metrics) domain**: an external exporter polls the BMC over IPMI and publishes a Prometheus endpoint, and Alloy scrapes that endpoint as an ordinary metrics target. There is no IPMI-specific configuration on the Alloy side.

#### 10.7.1. Labels

```text
ru.3ops.discovery.ipmi.enabled
ru.3ops.discovery.ipmi.address
ru.3ops.discovery.ipmi.module
ru.3ops.discovery.ipmi.secret-id
ru.3ops.discovery.ipmi.profile
```

The labels describe the intent (the BMC address, the exporter module, the secret, the profile), but the role of Alloy comes down to scraping the HTTP endpoint of an external exporter: there is no domain pipeline on the Alloy side as there is for snmp ([10.6](#106-domain-snmp)). Every ipmi label in `0.2` is declarative/inventory (neither the reference nor any domain pipeline reads them); `ipmi.profile` refers to the scrape profiles of section [8.2](#82-scrape-profiles) -- ipmi has no profile family of its own. The secret file is `/run/alloy-secrets/<secret-id>.ipmi` per the shared contract of section [9](#9-secret-contract); the BMC credentials are consumed by the exporter itself, not by Alloy.

The reference configuration ships no ipmi overlay (unlike [`037_snmp.alloy`](../alloy-optional/037_snmp.alloy)): the recommended path is to mark the `ipmi_exporter` container with the labels of the [metrics](#101-domain-metrics) domain and scrape it through the existing metrics pipeline. A dedicated overlay will appear only if Alloy gains a native IPMI component.

## 11. Validation rules

The minimal checks before a pipeline is created:

- `enabled == true` -- except for the logs domain (see section [10.3.1](#1031-default-collection-policy));
- `version` is supported (in `0.2` the check is reserved -- see section [5](#5-global-labels));
- `domain.enabled == true`;
- `type` belongs to the allowlist;
- `port` is a number in 1..65535;
- `profile` belongs to the profile allowlist of the domain (section [8](#8-profiles));
- `secret-id` matches the allowlist regex;
- `path` starts with `/`;
- `scheme` belongs to the allowlist.

An unknown `type` value drops the target entirely (fail-closed) and is reflected in the Alloy log where possible.

An empty value of any label is equivalent to the label being absent: the default of the corresponding domain applies (during relabeling a label with an empty value is removed, so empty values never reach the series).

The reference configuration implements the `path`, `scheme`, `profile` and `secret-id` checks with relabel rules. The `port` check is implicit and fail-closed: `keepequal` matches the declared port against the real private ports of the container, so a non-numeric, out-of-range or non-existent value drops the target.

The snmp file provider (overlay 037) checks its counterparts with the same fail-closed `discovery.relabel` keep rules on top of the `from_yaml` list: the `module` allowlist, the presence of `auth` and the presence of `address` -- a semantically invalid entry is dropped row by row. The `port` check through `keepequal` does not apply (there is no container). A separate **fail-STALE** mode applies as well: a syntactically broken device file as a whole breaks `from_yaml`, and Alloy holds on to the last valid arguments (the targets do not change -- this is not fail-closed and not an empty list). On a cold start there is no last valid value, so `discovery.relabel` is unhealthy and the target set is empty (the exporter starts with zero devices, healthy-idle). The row-by-row drop (semantics) and the whole-file fail-STALE (syntax) are two different modes.

## 12. Lifecycle

### 12.1. Adding a target

1. The container starts with `ru.3ops.discovery.enabled=true` (the logs domain is the exception: collection is on by default, section [10.3.1](#1031-default-collection-policy)).
2. `discovery.docker` discovers the container.
3. `discovery.relabel` checks the domain labels.
4. Alloy builds the corresponding pipeline.
5. The target appears in the Alloy UI.
6. Metrics or logs start reaching the backend.

### 12.2. Removing a target

1. The container is stopped or removed.
2. The target disappears from Docker discovery.
3. For the database domain the dynamic `foreach` pipeline is removed; the static scrape components of the other domains simply lose the target.
4. New telemetry samples stop arriving.
5. Historical data stays in the backend until retention expires.

### 12.3. Changing labels

Docker does not allow changing the labels of a running container. Changes take effect only after the container is recreated with the new labels.

## 13. Security requirements

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

If Alloy uses `/var/run/docker.sock`, the following must be taken into account:

- a read-only mount does not make the Docker API strictly read-only;
- access to the Docker socket is effectively highly privileged;
- a socket proxy allowing read endpoints only is preferable;
- the Alloy UI must not be published outward without authentication.

The requirement "Alloy must not be reachable from an untrusted Docker network" cannot be met in full, and that is a property of the model rather than an oversight in the configuration. Scraping a container means sharing a network with it, so a collector is always a neighbour of what it collects from: the Alloy HTTP server (`/metrics`, the unauthenticated `/api/v0/web/components`) and the opt-in OTLP receiver are visible to every container on that network. Splitting networks does not help -- with several networks `discovery.docker` takes only the alphabetically first one (section [14](#14-reference-implementation)), so the collector still has to sit in the network of the things it observes. What follows in practice: untrusted workloads are separated by a collector of their own, not by a network of the same one; on a shared network, assume neighbours can read the component list and its arguments (values marked `is_secret` are redacted).

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

- for the metrics and database domains SSRF is excluded by two conditions at once, and the second is as mandatory as the first. The scrape address is built only from `__meta_docker_network_ip` and a private port of the container itself (for database, from the secret file, which labels do not choose beyond `secret-id`), so labels cannot redirect collection to another host. The scrape response is an untrusted input too: `prometheus.scrape` follows redirects by default, and a container answering `302` with a link-local address would send the next request there on the collector's behalf. Every `prometheus.scrape` in the reference therefore sets `follow_redirects = false`; a configuration that does not meet this condition does not carry the guarantee;
- the blackbox domain is a deliberate exception: `blackbox.address` (section [10.4.1](#1041-labels)) points a probe at an arbitrary host, and the result (`probe_success`, the status, the certificate expiry) is visible in the metrics -- the container gains a network reachability oracle acting as Alloy. The probe port is limited to the private ports of the container itself, but the container declares its own exposed ports, so with untrusted neighbours `blackbox.address` should be constrained by an allowlist rule in `discovery.relabel`;
- the opt-in OTLP receiver (overlay [`060_otel`](../alloy-optional/060_otel.alloy)) listens without authentication and produces no provenance labels (section [10.5](#105-domain-otel)): network access to its ports equals the right to write telemetry with an arbitrary identity; the receiver should be kept on an internal network or fronted by an authenticating reverse proxy;
- `container` is added from the Docker engine metadata and `host` from the hostname of the Alloy collector; neither can be forged through labels (section [6.1](#61-labels-added-by-alloy));
- consequently, series and streams with forged `job`/`team`/`service_name` still carry the honest `container` and `host` of the sender: they do not merge with the data of the real owner and stay distinguishable -- but alert rules and dashboards that filter by `team`/`job` alone without regard for `container` will see the forged data too;
- fields taken from log content are not promoted into stream labels (section [6.2](#62-loki-label-cardinality));
- with untrusted neighbours on the host, the values of `team`/`environment`/`service_name` should additionally be constrained by allowlist rules in `discovery.relabel`; the reference configuration contains no such rules;
- the contract sets no limit on telemetry volume: a container can generate load through log volume and through the number of opt-in targets; the defence is rate limits on the backend side (Loki limits, remote_write endpoint limits).

## 14. Reference implementation

The reference Alloy configuration lives in the [`alloy/`](../alloy/) directory and is split across files. Every `*.alloy` file of the directory forms one configuration and they run together:

```sh
alloy run --stability.level=experimental alloy/
```

The `--stability.level=experimental` flag is required by the `foreach` block (experimental in Alloy v1.17). A syntax check without running:

```sh
docker run --rm -v "$PWD/alloy:/etc/alloy:ro" grafana/alloy:v1.17.1 \
  validate --stability.level=experimental /etc/alloy
```

The numeric prefix in the file names sets the reading order (the pipeline flow: discovery, then domains, then outputs). It does not affect how Alloy works: every file of the directory merges into a single component graph and cross-file references resolve regardless of order.

| File | Content |
|---|---|
| [`010_discovery.alloy`](../alloy/010_discovery.alloy) | `discovery.docker`: opt-in discovery for metrics/database and discovery of every container for logs |
| [`020_metrics.alloy`](../alloy/020_metrics.alloy) | The metrics domain: a shared relabel (validation plus provenance) and a `discovery.relabel`/`prometheus.scrape` pair per profile of section [8.2](#82-scrape-profiles) |
| [`030_database.alloy`](../alloy/030_database.alloy) | The database domain: a `foreach` pipeline per database type, the DSN from a secret file, the collection volume from `database.profile` (section [8.4](#84-database-profiles)) |
| [`035_blackbox.alloy`](../alloy/035_blackbox.alloy) | The blackbox domain: a shared `discovery.relabel` plus `prometheus.exporter.blackbox` (modules `http_2xx`/`tcp_connect`/`icmp`/`tls_connect`) and a filter-plus-scrape pair per profile of section [8.2](#82-scrape-profiles) |
| [`040_logs.alloy`](../alloy/040_logs.alloy) | The logs domain: relabel rules and `loki.source.docker` |
| [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy) | The profile dispatcher: `loki.process` with the base log profiles |
| [`090_outputs.alloy`](../alloy/090_outputs.alloy) | The outputs: `prometheus.remote_write` and `loki.write` |

The profile scrape pairs are layered: the shared domain relabel carries validation and provenance, while the thin `discovery.relabel`/`prometheus.scrape` pair per profile carries only the routing to its own interval. The names of profile components are derived mechanically from the full profile name (`fast-v1` becomes `metrics_fast_v1`). Targets that declare a profile outside the allowlist are deliberately scraped by no pair at all. An extra profile is added by copying the thin pair (filter plus scrape) with a changed regex in the profile rule, `scrape_interval` and `scrape_timeout`.

A known limitation of the reference configuration: `discovery.docker` creates a separate target per exposed TCP port of a container. The port fan-out is collapsed by `keepequal` rules (metrics, database, blackbox); logs are unaffected -- `loki.source.docker` deduplicates targets by container ID and reads a container exactly once. A container attached to several Docker networks produces no duplicate targets: by default (`match_first_network = true`) discovery creates targets for one network only, the first in alphabetical order of names. The multi-network risk lies elsewhere: the choice of network is deterministic but arbitrary, and if the first network by name is unreachable for Alloy, the targets of the metrics/database/blackbox domains point at an unreachable address (the target shows as `up == 0`); log collection does not depend on network reachability -- the lines are read through the Docker API. Containers with telemetry should be attached to a single network visible to Alloy.

The log read positions (`positions.yml`) and the `prometheus.remote_write` WAL live under the Alloy `--storage.path`. Without a persistent volume, recreating the Alloy container (an image update, `up --force-recreate`) causes the available container log history to be resent and the unsent metrics WAL to be lost; an ordinary process restart is safe (the writable layer of the container survives). For a production deployment the `--storage.path` directory should be placed on a persistent volume; the contract offers no delivery guarantee stronger than at-least-once.

### 14.1. Environment parameters

Deployment-specific values are configured through environment variables via `coalesce(sys.env("..."), <default>)`; when a variable is absent the default applies. The `RU_3OPS_DISCOVERY_` prefix stands for 3ops Discovery.

| Variable | Purpose | Default |
|---|---|---|
| `RU_3OPS_DISCOVERY_DOCKER_HOST` | The Docker daemon address | `unix:///var/run/docker.sock` |
| `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` | The target list refresh interval | `30s` |
| `RU_3OPS_DISCOVERY_SECRETS_DIR` | The directory of secret files (see [9](#9-secret-contract)) | `/run/alloy-secrets` |
| `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL` | The metrics endpoint (Prometheus remote_write protocol) | `http://prometheus:9090/api/v1/write` |
| `RU_3OPS_DISCOVERY_LOKI_PUSH_URL` | The logs endpoint (Loki push API) | `http://loki:3100/loki/api/v1/push` |
| `RU_3OPS_DISCOVERY_HOST_ROOTFS_PATH` | The mount point of the host root FS for `prometheus.exporter.unix` (optional file 070) | `/rootfs` |
| `RU_3OPS_DISCOVERY_HOST_PROCFS_PATH` | The procfs mount point for the host exporter | `/host/proc` |
| `RU_3OPS_DISCOVERY_HOST_SYSFS_PATH` | The sysfs mount point for the host exporter | `/host/sys` |
| `RU_3OPS_DISCOVERY_SNMP_TARGETS_FILE` | The path to the snmp device file (not a secret; overlay 037) | `/etc/alloy/snmp_targets.yaml` |

The scrape profile parameters (interval/timeout) are not configurable through environment variables: they are part of the contract (see [8.2](#82-scrape-profiles)), not deployment configuration.

Do not embed credentials into endpoint URLs (`https://user:pass@host`): the value of a variable is an ordinary string and may show up in the Alloy UI and in the logs. For authentication use the `basic_auth`/`authorization` blocks inside `endpoint` with a secret from `local.file` (`is_secret = true`).

### 14.2. Backends

The file [`090_outputs.alloy`](../alloy/090_outputs.alloy) is the single integration point with the storage systems; replacing a backend does not touch the discovery and pipeline files. Alloy is not limited to the Prometheus plus Loki pair:

- `prometheus.remote_write` works with any remote_write-compatible storage: Mimir, VictoriaMetrics, Thanos, Grafana Cloud.
- `loki.write` works with any endpoint implementing the Loki push API.
- For OTLP backends (Tempo, vendor APM) the streams are converted through `otelcol.receiver.prometheus` / `otelcol.receiver.loki` and exported by `otelcol.exporter.otlp`.

Swapping a single URL is enough only for unauthenticated endpoints. Mimir and Grafana Cloud require authentication and/or the `X-Scope-OrgID` header: beyond the variables of section [14.1](#141-environment-parameters) you will need to add `basic_auth`/`authorization`/`headers` blocks to [`090_outputs.alloy`](../alloy/090_outputs.alloy) -- with a secret from `local.file`, not in the URL (see the warning in [14.1](#141-environment-parameters)).

This is not a complete production configuration but the base structure of a manifest implementation. Explanations of the non-obvious parts (target deduplication by container ID, the keep rule for `secret-id`, the correspondence with scrape profiles) live in the comments of the files themselves.

### 14.3. Customizing the reference configuration

Alloy merges every `*.alloy` file of a directory into a single component graph (top level, non-recursively); component names are globally unique. A base component cannot be overridden: two declarations with the same name are a load error, not an override. Customization is done in three ways:

- **an overlay directory** -- extra files added to the base directory at materialization time (section [14.5](#145-optional-files)); the base `alloy/` stays valid and complete without them;
- **extension points** -- stable exports of the base that an overlay may reference (section [14.4](#144-extension-points));
- **env parameterization** -- deployment values through `RU_3OPS_DISCOVERY_*` (section [14.1](#141-environment-parameters)).

Conventions against collisions: repository files use the numeric prefixes `0xx`, user overlays use `1xx` and above; user component names use the `ext_` prefix. The base/optional boundary criterion: the base `alloy/` contains exactly what is driven by discovery through Docker labels, while anything static, host-level or requiring deployment privileges is moved into optional.

Privileged overlays receive host-level deployment privileges and observe the host or all of its containers as a whole, outside the discovery scope: [`070_host-metrics`](../alloy-optional/070_host-metrics.alloy) (host procfs/sysfs/rootfs), [`080_host-logs`](../alloy-optional/080_host-logs.alloy) (systemd journal), [`075_container-metrics`](../alloy-optional/075_container-metrics.alloy) (the host cgroup namespace plus `/sys/fs/cgroup:ro`; the host PID namespace is neither required nor granted). Granting such privileges is a deliberate deployment decision, not a default.

### 14.4. Extension points

The public API of the base configuration: the stable exports an overlay file may reference. They are stable within a minor version of the contract; renaming one is a breaking change.

| Export | Component |
|---|---|
| `prometheus.remote_write.default.receiver` | [`090_outputs.alloy`](../alloy/090_outputs.alloy) |
| `loki.write.default.receiver` | [`090_outputs.alloy`](../alloy/090_outputs.alloy) |
| `loki.process.docker_profiles.receiver` | [`050_log-profiles.alloy`](../alloy/050_log-profiles.alloy) |
| `discovery.docker.containers.targets` | [`010_discovery.alloy`](../alloy/010_discovery.alloy) |
| `discovery.docker.docker_logs.targets` | [`010_discovery.alloy`](../alloy/010_discovery.alloy) |

### 14.5. Optional files

The [`alloy-optional/`](../alloy-optional/) directory holds overlay files added to the base directory at materialization time. The base `alloy/` is valid without them.

| File | Content |
|---|---|
| [`060_otel.alloy`](../alloy-optional/060_otel.alloy) | Opt-in OTLP receiver: `otelcol.receiver.otlp`, with metrics going to `prometheus.remote_write` and logs to `loki.write` through an allowlist processor |
| [`070_host-metrics.alloy`](../alloy-optional/070_host-metrics.alloy) | Opt-in host metrics: `prometheus.exporter.unix` (`node_*` series) into `prometheus.remote_write`; rootfs/procfs/sysfs through `RU_3OPS_DISCOVERY_HOST_*`; provenance per [6.1](#61-labels-added-by-alloy): `host`/`collector` are added by `discovery.relabel` before the scrape |
| [`075_container-metrics.alloy`](../alloy-optional/075_container-metrics.alloy) | Opt-in per-container metrics: `prometheus.exporter.cadvisor` (series `container_cpu_*`/`container_memory_*`/`container_network_*`; `container_fs_*` is outside the perimeter) into `prometheus.remote_write`. The Docker API goes through `docker_host` (reusing `RU_3OPS_DISCOVERY_DOCKER_HOST`, socket proxy: a GET allowlist of the `CONTAINERS`/`INFO`/`VERSION`/`PING` sections is enough); with the Docker API unavailable the output is practically empty (`docker_only`). Provenance per [6.1](#61-labels-added-by-alloy): allowlisted container labels become `environment`/`team`/`compose_*`, `name` becomes `container`; raw `container_label_*`/`id`/`name` are dropped; `instance` is the collector hostname and `job` is `integrations/cadvisor` (the exporter's own label; both are deliberate gaps). Cardinality: `store_container_labels = false` plus the allowlist, root cgroup statistics disabled, `disabled_metrics`/`enabled_metrics` tunable. Deployment privileges (the host cgroup namespace) are covered in section [14.3](#143-customizing-the-reference-configuration); per-container opt-out is not supported. |
| [`080_host-logs.alloy`](../alloy-optional/080_host-logs.alloy) | Opt-in host logs: `loki.source.journal` (systemd journal) into `loki.write`; the static labels `host`/`collector`/`source` (allowlisted in [6.2](#62-loki-label-cardinality)) |
| [`037_snmp.alloy`](../alloy-optional/037_snmp.alloy) | The snmp domain (opt-in overlay): the file provider (`local.file` plus `encoding.from_yaml`), `prometheus.exporter.snmp` (modules `if_mib`/`system`, profile `snmp-standard-v1`), auth from an inline `config` secret (`local.file` with `is_secret`) through merge. Enabled only together with the device and auth files (a top-level `local.file` without a file is unhealthy). |

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
  (section [4](#4-docker-label-normalization-in-alloy)).

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
