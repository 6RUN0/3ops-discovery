# Alloy reference implementation

The Grafana Alloy configuration that implements every domain of the
3ops Discovery contract. The normative parts live in the manifest,
section [14.4](../docs/manifest.md#144-reference-implementation-alloy):
the pinned Alloy tag, the run and `validate` commands, the base file
table, customization ([14.4.1](../docs/manifest.md#1441-customization)),
extension points ([14.4.2](../docs/manifest.md#1442-extension-points))
and the optional files of [`../alloy-optional/`](../alloy-optional/)
([14.4.3](../docs/manifest.md#1443-optional-files)). This file explains
how the configuration is built; it adds no requirement.

This is not a complete production configuration but the base structure
of a manifest implementation. Explanations of the non-obvious parts
(target deduplication by container ID, the keep rule for `secret-id`,
the correspondence with scrape profiles) live in the comments of the
files themselves.

## File order

The numeric prefix in the file names sets the reading order (the
pipeline flow: discovery, then domains, then outputs). It does not
affect how Alloy works: every file of the directory merges into a single
component graph and cross-file references resolve regardless of order.

## Environment parameters

Every deployment value of manifest section
[14.1](../docs/manifest.md#141-environment-parameters) is read as
`coalesce(sys.env("..."), <default>)`, so an unset variable falls back
to the default of that table.

## Layered profile pairs

The profile scrape pairs are layered: the shared domain relabel carries
validation and provenance, while the thin
`discovery.relabel`/`prometheus.scrape` pair per profile carries only
the routing to its own interval. The names of profile components are
derived mechanically from the full profile name (`fast-v1` becomes
`metrics_fast_v1`). Targets that declare a profile outside the allowlist
are deliberately scraped by no pair at all. An extra profile is added by
copying the thin pair (filter plus scrape) with a changed regex in the
profile rule, `scrape_interval` and `scrape_timeout`.

## Per-port fan-out and multiple networks

`discovery.docker` creates a separate target per exposed TCP port of a
container. The port fan-out is collapsed by `keepequal` rules (metrics,
database, blackbox); logs are unaffected: `loki.source.docker`
deduplicates targets by container ID and reads a container exactly once.

A container attached to several Docker networks produces no duplicate
targets: by default (`match_first_network = true`) discovery creates
targets for one network only, the first in alphabetical order of names.
The multi-network risk lies elsewhere: the choice of network is
deterministic but arbitrary, and if the first network by name is
unreachable for Alloy, the targets of the metrics/database/blackbox
domains point at an unreachable address (the target shows as
`up == 0`). Log collection does not depend on network reachability: the
lines are read through the Docker API. Containers with telemetry should
be attached to a single network visible to Alloy.

## Outputs and stores

[`090_outputs.alloy`](090_outputs.alloy) is the single integration point
with the stores; replacing a store does not touch the discovery and
pipeline files. Alloy is not limited to the Prometheus plus Loki pair:

- `prometheus.remote_write` works with any remote_write-compatible
  store: Mimir, VictoriaMetrics, Thanos, Grafana Cloud.
- `loki.write` works with any endpoint implementing the Loki push API,
  VictoriaLogs included.
- For OTLP backends (Tempo, vendor APM) the streams are converted
  through `otelcol.receiver.prometheus` / `otelcol.receiver.loki` and
  exported by `otelcol.exporter.otlp`.

Swapping a single URL is enough only for unauthenticated endpoints.
Mimir and Grafana Cloud require authentication and/or the
`X-Scope-OrgID` header: beyond the variables of manifest section 14.1,
add `basic_auth`/`authorization`/`headers` blocks inside `endpoint` in
`090_outputs.alloy`, with the secret read from `local.file`
(`is_secret = true`). Credentials never go into the URL (manifest
section [14.2](../docs/manifest.md#142-output-protocols-and-stores)):
the variable value is an ordinary string and may show up in the Alloy UI
and in the logs.

## State and persistent storage

The log read positions (`positions.yml`) and the
`prometheus.remote_write` WAL live under the Alloy `--storage.path`.
Without a persistent volume, recreating the Alloy container (an image
update, `up --force-recreate`) resends the available container log
history and loses the unsent metrics WAL; an ordinary process restart is
safe (the writable layer of the container survives). For a production
deployment place the `--storage.path` directory on a persistent volume;
the contract offers no delivery guarantee stronger than at-least-once.
