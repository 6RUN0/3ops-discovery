# 3ops Discovery

A declarative contract for automatic discovery and configuration of
telemetry targets in [Grafana Alloy](https://grafana.com/docs/alloy/)
driven by Docker labels. An application declares how it wants to be
collected through `ru.3ops.discovery.*` labels on its own container --
Alloy picks them up on its own, with no edit to the collector
configuration.

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

The namespace is reverse-DNS derived from the `3ops.ru` domain. The
prefix is deliberately **not** `x-`: Docker Compose treats an
`x-`-prefixed key inside a `labels:` mapping as an extension and drops it
silently, while a reverse-DNS key survives both the map and the list
form.

## What is in the repository

The repository is the contract itself, its reference implementation, and
the gates that bind the two together and keep them from drifting apart.

| Path | Purpose |
|---|---|
| [`docs/manifest.ru.md`](docs/manifest.ru.md) | The normative contract (Russian). The single source of truth: label names, domains, profiles, the secret contract, security requirements, the Alloy version pin. |
| [`docs/manifest.md`](docs/manifest.md) | English translation of the manifest. Provided for readers; not normative and not covered by the gates. |
| `alloy/*.alloy` | The reference Alloy configuration: discovery, metrics, database, logs, log profiles, outputs. |
| `tests/static/` | Static gates: they check the normative facts of the manifest against the actual configuration in both directions. |
| `tests/e2e/` | End-to-end stack (`docker compose`): metrics and logs really do reach Prometheus and Loki; alloy/prometheus/loki monitor themselves through the contract (dogfooding). |
| [`tools/materialize.py`](tools/materialize.py) | Assembles the configuration directory (base union optional) for `alloy_check` and e2e. |
| `LICENSE` | MIT license. |

The manifest is Russian by design; code, comments and commits are
English.

## Requirements

- [uv](https://docs.astral.sh/uv/) -- the only environment manager.
- Python 3.13+.
- Docker -- for the `alloy_check` and `e2e` gates.
- System binaries for `docs_lint`: `rumdl`, `typos`, `lychee`.

## Quality gates

Everything runs through `uv run nox`.

| Command | What it does | Docker / network |
|---|---|:---:|
| `uv run nox` | Default gates: `lint` + `docs_lint` + `alloy_check` + `tests`. | yes |
| `uv run nox -s lint tests` | Fully offline: pre-commit plus the static gates. | no |
| `uv run nox -s lint` | pre-commit over all files. | no |
| `uv run nox -s docs_lint` | `rumdl` + `typos` + `lychee`. | network |
| `uv run nox -s alloy_check` | `alloy fmt -t` + `validate` for every directory combination inside the pinned image. | Docker |
| `uv run nox -s tests` | Static manifest-vs-config gates plus mini-app units. | no |
| `uv run nox -s e2e` | Delivery checks against a live compose stack (minutes). | Docker |
| `uv run nox -s preflight` | Everything at once. | yes |

The Alloy image is pinned **by the manifest** (section [14](docs/manifest.md#14-reference-implementation));
`noxfile.ALLOY_IMAGE` must match -- a static test enforces it.

## Releasing

`uv run nox -s release` builds `dist/3ops-discovery-<version>.tar.gz`
and `SHA256SUMS`: the contract, the reference configuration, the overlay
files and a deployment README. The version comes from the manifest
header, the only place it is written down (`pyproject.toml` says `0.0.0`
on purpose). The contents are enumerated by `git ls-files`, so untracked
scratch never reaches the archive, and the build is reproducible: a
rebuild yields the same sha256. Publishing is a workflow on a `vX.Y.Z`
tag, which must match the manifest version.

## How it holds together

The static gates extract normative facts from [`docs/manifest.ru.md`](docs/manifest.ru.md)
(by anchors: section number plus position) and from `alloy/*.alloy` (with
a regex scanner), then compare them. Restructuring the manifest breaks
the gates loudly. Deliberately allowed divergences are listed in a single
table in [`tests/static/asymmetries.py`](tests/static/asymmetries.py). Contract values (scrape
intervals, label names, defaults) are only ever changed in the manifest
-- never "to make a test pass".

## Contract basics

- **Domains:** `metrics`, `database`, `logs`, `blackbox`, `otel`, `snmp`,
  `ipmi` -- under the keys `ru.3ops.discovery.<domain>.<key>`.
- **Secrets** are passed as a logical identifier rather than a value
  (`ru.3ops.discovery.database.secret-id`); the secrets themselves reach
  neither labels nor git.
- **Deployment env parameters** use the `RU_3OPS_DISCOVERY_*` prefix (for
  example `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL`), mirroring the label
  namespace.

The full description lives in [`docs/manifest.md`](docs/manifest.md)
(normative original: [`docs/manifest.ru.md`](docs/manifest.ru.md)).

## Conventions

- Conventional Commits, no AI attribution in trailers.
- Versions of external artifacts (packages, images, hook revisions) are
  pinned from live sources, never from memory.
- No secrets in git, not even fake ones: `*.dsn` and the like are
  generated by fixtures into gitignored temporary directories.
