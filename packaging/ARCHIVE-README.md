# 3ops Discovery

A declarative contract for automatic discovery and configuration of
telemetry targets, driven by Docker labels. An application declares how
it wants to be collected through `ru.3ops.discovery.*` labels on its own
container, and a collector picks them up with no edit to the collector
configuration.

This archive ships the contract, its reference implementation on Grafana
Alloy, the vmagent implementation of the metrics domain and the Vector
implementation of the logs domain. It becomes `README.md` in the archive
root; the repository README covers the quality gates instead and is not
shipped here.

## Contents

| Path | What it is |
|---|---|
| `docs/manifest.ru.md` | The normative contract (Russian). The source of truth for label names, domains, profiles, secrets and the pinned Alloy version. |
| `docs/manifest.md` | English translation. Provided for readers; on any discrepancy the Russian original wins. |
| `implementations/alloy/base/` | The reference configuration. Every file together forms one component graph. |
| `implementations/alloy/optional/` | Opt-in overlay files. The base is valid and complete without them. |
| `implementations/alloy/README.md` | How the reference configuration is built and how to compose it by domain. |
| `implementations/vmagent/` | A second implementation of the metrics domain on VictoriaMetrics vmagent, with its own README. |
| `implementations/vector/` | A second implementation of the logs domain on Vector, with its own README. |
| `CHANGELOG.md`, `CHANGELOG.ru.md` | What changed between contract versions. |
| `LICENSE` | MIT. |

## Running it

The base configuration alone:

```sh
alloy run --stability.level=experimental implementations/alloy/base/
```

The configuration is composed by domain: each file belongs to one or more
domains (manifest sections 14.4 and 14.4.3), and a deployment takes the
union of the files of the domains it chooses. The
`--stability.level=experimental` flag is needed only when the set includes
the database domain, whose `foreach` block requires it. Check the syntax
without running:

```sh
docker run --rm -v "$PWD/implementations/alloy/base:/etc/alloy:ro" grafana/alloy:v1.21.2 \
  validate --stability.level=experimental /etc/alloy
```

The image tag is pinned by the manifest (section 14.4). Use that tag: the
configuration is validated against it and nothing else.

## Running the metrics domain on vmagent

The metrics domain can run on vmagent instead of Alloy (manifest section
14). One collector serves a domain on a host, never two, so vmagent
then serves both metrics and ipmi: an ipmi exporter is scraped as an
ordinary metrics target (section 10.7). The Alloy directory is the union
of the files of the domains Alloy still serves (the `Domains` column of
manifest sections 14.4 and 14.4.3). Do not delete every file listed for
metrics: `010_discovery-scrape.alloy` and `090_output-metrics.alloy` are
shared with other domains, and without them Alloy rejects the whole
directory. For the default set this leaves out only `020_metrics.alloy`.
Start vmagent through its entrypoint, which applies the section 14.1
defaults:

```sh
docker run -d --name vmagent \
  -v "$PWD/implementations/vmagent:/etc/vmagent:ro" \
  -e RU_3OPS_DISCOVERY_DOCKER_HOST=tcp://docker-socket-proxy:2375 \
  -e RU_3OPS_DISCOVERY_REMOTE_WRITE_URL=http://victoriametrics:8428/api/v1/write \
  -e RU_3OPS_DISCOVERY_HOSTNAME="$(hostname)" \
  -v vmagent-data:/vmagent-remotewrite-data \
  --entrypoint /bin/sh \
  victoriametrics/vmagent:v1.154.1 /etc/vmagent/entrypoint.sh
```

Give `RU_3OPS_DISCOVERY_HOSTNAME` one value on every collector of the
host, Alloy included (here the host's own name): manifest section 14
requires it and names what breaks when it is unset.

The image tag is pinned by the manifest registry (section 14). Appending
`-dryRun` checks the configuration and exits. The Docker API access, the
variables and the differences from Alloy are in
`implementations/vmagent/README.md`.

## Running the logs domain on Vector

The logs domain can run on Vector instead of Alloy (manifest section 14).
One collector serves a domain on a host, never two, so the Alloy
directory is the union of the files of the remaining domains (manifest
sections 14.4 and 14.4.3 list files by domain). That leaves out
`011_discovery-logs.alloy`, `040_logs.alloy` and `050_log-profiles.alloy`,
and `091_output-logs.alloy` too unless Alloy serves the otel or host-logs
domain, so for the default set all four leave. Start Vector through its
entrypoint, which applies the section 14.1 defaults and splits the push
URL; give the container a `--hostname` that is not a prefix of its ID, or
Vector does not collect its own logs:

```sh
docker run -d --name vector \
  --hostname vector-collector \
  -v "$PWD/implementations/vector:/etc/vector:ro" \
  -v vector-data:/var/lib/vector \
  -e RU_3OPS_DISCOVERY_DOCKER_HOST=tcp://docker-socket-proxy:2375 \
  -e RU_3OPS_DISCOVERY_LOKI_PUSH_URL=http://loki:3100/loki/api/v1/push \
  -e RU_3OPS_DISCOVERY_HOSTNAME="$(hostname)" \
  --entrypoint /bin/sh \
  timberio/vector:0.60.0-alpine /etc/vector/entrypoint.sh
```

Give `RU_3OPS_DISCOVERY_HOSTNAME` one value on every collector of the
host, Alloy and vmagent included (here the host's own name): manifest
section 14 requires it and names what breaks when it is unset.

The `vector-data` volume holds `data_dir` (`/var/lib/vector`). The
configuration stores no log read positions there, and Vector 0.60.0
starts with nothing writable on that path, so the volume is optional.
The image tag is pinned by the manifest registry (section 14).
Replacing `/etc/vector/entrypoint.sh` with
`/etc/vector/entrypoint.sh validate --no-environment` checks the
configuration and exits. Lines written while Vector is down are lost,
and the variables and other differences from Alloy are in
`implementations/vector/README.md`.

## Adding an overlay

Alloy merges every `*.alloy` file of a single directory into one graph,
so composition is a copy -- there is no include directive:

```sh
mkdir -p /etc/alloy
cp implementations/alloy/base/*.alloy /etc/alloy/
cp implementations/alloy/optional/070_host-metrics.alloy /etc/alloy/
```

Overlay files and what they need:

| File | Adds | Requires |
|---|---|---|
| `060_otel.alloy` | OTLP receiver | Nothing; listens without authentication, keep it on an internal network |
| `070_host-metrics.alloy` | Host metrics (`node_*`) | Host rootfs/procfs/sysfs mounts |
| `075_container-metrics.alloy` | Per-container metrics | Host cgroup namespace, `/sys/fs/cgroup:ro` |
| `080_host-logs.alloy` | Host logs from the systemd journal | A persistent journal on the host |
| `037_snmp.alloy` | The snmp domain | The device and auth files present on disk; the graph goes unhealthy without them |

## Configuring the deployment

Deployment-specific values come from environment variables; each falls
back to a default when unset. The full table is in section 14.1 of the
manifest. The ones most deployments set:

```sh
RU_3OPS_DISCOVERY_REMOTE_WRITE_URL=http://prometheus:9090/api/v1/write
RU_3OPS_DISCOVERY_LOKI_PUSH_URL=http://loki:3100/loki/api/v1/push
RU_3OPS_DISCOVERY_DOCKER_HOST=unix:///var/run/docker.sock
RU_3OPS_DISCOVERY_HOSTNAME="$(hostname)"
RU_3OPS_DISCOVERY_SECRETS_DIR=/run/alloy-secrets
```

Scrape intervals and timeouts are deliberately absent: they are part of
the contract (section 8.2), selected by profile, not by deployment.

Two operational requirements the manifest states and a first deployment
usually misses:

- Give `--storage.path` a persistent volume. Log read positions and the
  metrics WAL live there, so recreating the container without one
  resends log history and loses unsent metrics.
- Do not put credentials in the endpoint URLs. A variable value is an
  ordinary string and may surface in the Alloy UI and logs; use the
  `basic_auth`/`authorization` blocks with a secret from `local.file`.

## Labelling an application

The minimal contract for a service that already exposes a Prometheus
endpoint:

```yaml
services:
  orders-api:
    image: example/orders-api:latest
    labels:
      ru.3ops.discovery.enabled: "true"
      ru.3ops.discovery.metrics.enabled: "true"
      ru.3ops.discovery.metrics.type: "prometheus"
      ru.3ops.discovery.metrics.port: "8000"
      ru.3ops.discovery.metrics.job: "orders-api"
```

Logs need no labels at all: stdout/stderr of every container is
collected by default, and `ru.3ops.discovery.logs.enabled: "false"` is
the opt-out.

Read section 13 of the manifest before exposing this to workloads you do
not control: labels are declared by the container itself, so the right
to start a container is the right to declare any `job`, `team` or
`environment` value.
