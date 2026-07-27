# 3ops Discovery

A declarative contract for automatic discovery and configuration of
telemetry targets in Grafana Alloy, driven by Docker labels. An
application declares how it wants to be collected through
`ru.3ops.discovery.*` labels on its own container, and Alloy picks them
up with no edit to the collector configuration.

This archive ships the contract and its reference implementation. It
becomes `README.md` in the archive root; the repository README covers
the quality gates instead and is not shipped here.

## Contents

| Path | What it is |
|---|---|
| `docs/manifest.ru.md` | The normative contract (Russian). The source of truth for label names, domains, profiles, secrets and the pinned Alloy version. |
| `docs/manifest.md` | English translation. Provided for readers; on any discrepancy the Russian original wins. |
| `alloy/` | The reference configuration. Every file together forms one component graph. |
| `alloy-optional/` | Opt-in overlay files. The base is valid and complete without them. |
| `CHANGELOG.md`, `CHANGELOG.ru.md` | What changed between contract versions. |
| `LICENSE` | MIT. |

## Running it

The base configuration alone:

```sh
alloy run --stability.level=experimental alloy/
```

The `--stability.level=experimental` flag is required by the `foreach`
block used by the database domain. Check the syntax without running:

```sh
docker run --rm -v "$PWD/alloy:/etc/alloy:ro" grafana/alloy:v1.17.1 \
  validate --stability.level=experimental /etc/alloy
```

The image tag is pinned by the manifest (section 14). Use that tag: the
configuration is validated against it and nothing else.

## Adding an overlay

Alloy merges every `*.alloy` file of a single directory into one graph,
so composition is a copy -- there is no include directive:

```sh
mkdir -p /etc/alloy
cp alloy/*.alloy /etc/alloy/
cp alloy-optional/070_host-metrics.alloy /etc/alloy/
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
