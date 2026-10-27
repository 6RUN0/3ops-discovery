# 3ops Discovery

Specification of a labels-driven telemetry discovery contract that any
collector can implement (`docs/manifest.ru.md`, normative, Russian), its
series catalog (`docs/series/`), the reference implementation in Grafana
Alloy (`implementations/alloy/base/*.alloy`,
`implementations/alloy/optional/*.alloy`) and the quality gates that
bind them together.

## Commands

- `uv run nox` - default gates: lint + docs_lint + alloy_check +
  vmagent_check + vector_check + tests. Honestly requires Docker
  (alloy_check, vmagent_check, vector_check) and network (lychee); the
  fully offline set is `uv run nox -s lint tests`.
- `uv run nox -s lint` - pre-commit hooks on all files. pre-commit is
  not installed as a git hook here, so only this session runs it; its
  detect-secrets hook rewrites `.secrets.baseline` line numbers after
  any edit above a recorded finding, so stage the baseline after lint.
- `uv run nox -s docs_lint` — rumdl + typos + lychee (system binaries).
- `uv run nox -s alloy_check` — `alloy fmt -t` + `validate` for every
  config combination, inside the pinned Docker image.
- `uv run nox -s vmagent_check` - `implementations/vmagent/` through its
  `entrypoint.sh` with `-dryRun` (strict parse) in `noxfile.VMAGENT_IMAGE`,
  once with no env (14.1 defaults) and once with the e2e values. vmagent
  keeps an unset `%{NAME}` placeholder as literal text and still passes
  `-dryRun`, so a placeholder without an entrypoint default is caught only
  by `tests/static/test_vmagent_config.py`.
- `uv run nox -s vector_check` - `implementations/vector/` through its
  `entrypoint.sh` with `vector validate --no-environment --deny-warnings`
  in `noxfile.VECTOR_IMAGE`, once with no env and once with the e2e
  values; it compiles the VRL and fails on an unset `${NAME}`. Without
  `--dangerously-allow-env-var-interpolation` Vector keeps `${NAME}` as
  literal text and validate still passes, and a bare `$` before a
  non-word character passes too, so both are caught only by
  `tests/static/test_vector_config.py`.
- `uv run nox -s tests` — static manifest-vs-config gates + mini-app
  units (no Docker).
- `uv run nox -s e2e` — docker compose delivery checks (opt-in, takes
  minutes). Subset: `uv run nox -s e2e -- -k logs_delivery` (a file
  path after `--` does not narrow the run: the session always passes
  the whole `tests/e2e` directory to pytest, so filter with `-k`).
- `uv run nox -s e2e -- -m "not alloy_internals"` - contract conformance
  subset: checks that do not read Alloy internals, so a second
  implementation can run them.
- `uv run nox -s e2e_victoria` - the same e2e suite with VictoriaMetrics +
  VictoriaLogs as the storage (`tests/e2e/stack/docker-compose.victoria.yml`
  overlay); takes `-- -k ...` like `e2e`.
- `uv run nox -s e2e_vmagent` / `uv run nox -s e2e_vmagent_victoria` -
  the contract subset (`-m "not alloy_internals"`) with vmagent as the
  metrics-domain collector, on Prometheus + Loki / on the Victoria stores.
  Run e2e sessions one at a time: they share one Docker daemon.
- `uv run nox -s preflight` — everything.
- `uv run nox -s release` — build `dist/<name>-<version>.tar.gz` +
  `SHA256SUMS` (contract + reference config + overlays + deployment
  README). Not a gate, so not in `preflight`; its invariants (version
  from the manifest header only, `.alloy` set == what `alloy_check`
  validates, reproducible bytes) live in `tests/static/test_release.py`.
- `uv run python -m tools.series_catalog snapshot --metrics-url
  http://127.0.0.1:<prometheus port> --project xad-demo` - prints, as
  YAML, the series and label names a running stack serves for every
  catalog probe; raw material for editing `docs/series/`, never copied in
  unreviewed. Run it against `nox -s demo` after every target has been
  scraped once: a cell scraped zero times comes out empty.
- `uv run nox -s demo` — interactive sandbox: full stack + Grafana
  (`--profile demo`, anonymous access at `http://127.0.0.1:3000`,
  Prometheus + Loki datasources provisioned). Prints URLs, follows logs;
  Ctrl+C detaches, `uv run nox -s demo -- down` tears it down. Not part of
  `preflight` (interactive).

## Architecture

- `docs/manifest.ru.md` — the contract; normative tables/blocks are
  extracted by ANCHORS (section number + position) in
  `tests/static/manifest_doc.py`. Restructuring the manifest breaks
  the gates loudly; deliberate counterexamples in the text are never
  extracted.
- `implementations/alloy/base/*.alloy` - reference config, the default
  domains; one materialized directory = one merged component graph,
  unique component names, no overrides possible.
- `docs/manifest.md` - English translation; not normative, but
  `tests/static/test_translation.py` demands the same structure as the
  Russian original (headings, section numbers, list items, table rows),
  so both files change in one commit. Sections 1-13 name no
  implementation: `tests/static/test_manifest_neutrality.py` allows
  implementation mentions only in the sections listed in
  `asymmetries.MANIFEST_IMPLEMENTATION_MENTIONS` (1 and 14); reference
  mechanics go to 14.4.4.
- `docs/series/<domain>.yaml` - the series catalog (manifest 14.3), a
  lower bound on series and identity label names per profile or module.
  Rebuild it from a snapshot (command above) whenever the Alloy pin
  changes, since embedded exporters move with it. Gates:
  `tests/static/test_series_catalog.py` (schema; an unknown key or empty
  `present` is a `CatalogError`), `tests/e2e/test_series_parity.py` (the
  collector of each cell's domain serves it: `Stack.collector(domain)`
  picks the `SERIES_PARITY_GAPS` rows, so under `e2e_vmagent` the
  `metrics/scrape` cell is vmagent's; an implementation literal there
  fails `tests/static/test_implementation_gaps.py`, which also keeps every
  implementation-keyed asymmetries row inside its manifest 14 registry
  row) and `tests/e2e/test_log_fields_parity.py`
  (non-indexed fields per log profile equal the 8.3 table; fields a
  store adds itself are listed per store in
  `asymmetries.STORE_DERIVED_LOG_FIELDS`).
- `implementations/alloy/optional/*.alloy` - opt-in overlay files
  (manifest §14.4.3):
  `037_snmp` (snmp domain; loads only with its device and auth files,
  `tools.materialize.PROVIDER_FILES`), `060_otel` (OTLP receiver),
  `070_host-metrics` (`prometheus.exporter.unix`, `node_*` series),
  `075_container-metrics` (`prometheus.exporter.cadvisor`, needs the host
  cgroup namespace), `080_host-logs` (`loki.source.journal`).
- Composition is by domain: `tools.materialize.DOMAIN_FILES` maps each
  domain of the manifest 14 registry to its files in `base/` and
  `optional/` (the `Домены` column of manifest tables 14.4 and 14.4.3,
  `tests/static/test_domain_files.py`). `COMBOS` maps a combo name to
  domains: `base`, `all` (no snmp), `all-snmp` and `domain-<d>` for each
  domain alone; alloy_check validates every combo. The e2e main fixture
  loads `all` (080 reads the journal of `journal-host`, below), the snmp
  fixture `all-snmp`.
- `tests/static/` — manifest vs config consistency; allowed gaps live
  in `asymmetries.py` as one explicit table.
- `tests/e2e/stack/` — compose stack: Alloy reaches the Docker API
  only through docker-socket-proxy (GET-only, internal network);
  alloy/prometheus/loki monitor themselves through the contract
  labels (dogfooding).
- `tests/e2e/stack/journal-host/` + `docker-compose.journal-host.yml` -
  e2e-only overlay: systemd as PID 1 (debian:trixie-slim, `tmp.mount`
  masked) writing a persistent journal into the named volume `journal`,
  which alloy mounts read-only for 080. It exists because CI runners and
  many dev hosts keep no persistent journal, so a host mount left 080
  unproven. Run conditions: `cgroup: host`, `/sys/fs/cgroup` read-write,
  tmpfs `/run` and `/run/lock`; missing any of them, it exits 255 at once
  with empty `docker logs`. `cgroup: host` plus the rw cgroup mount grant
  the container write access to the host cgroup tree, so only the e2e
  fixtures pass the overlay (`-f`); `nox -s demo` uses
  `noxfile.DEMO_COMPOSE_FILES` without it and drops 080
  (`DEMO_EXCLUDED_DOMAINS`), pinned by `tests/static/test_demo.py`. The
  fixture blocks on `systemctl is-system-running --wait` (via
  `docker compose exec`) before tests run and fails at once if the
  container exited; diagnostics (container status, exit code, `docker
  logs`, `systemctl --failed`, journal tail) land in
  `tests/e2e/_artifacts/<project>/journal-host-*.txt`. An e2e run without
  a cached image needs network: the build runs `apt-get` against
  deb.debian.org (about 2.5 min cold).
- `tools/materialize.py` - builds the config dir (the union of the
  chosen domains' files) for alloy_check, the e2e mount and the demo.
- e2e storage: `RU_3OPS_DISCOVERY_E2E_BACKEND` (`prometheus-loki`, the
  default, or `victoria`; anything else is a usage error before docker
  starts) picks the `BackendSpec` in `tests/e2e/conftest.py`; checks query
  logs through `tools.backends.LogQuery`, so one test runs on either store.
  In the victoria variant Prometheus and Loki still run (the base compose
  makes `alloy` depend on them) but receive nothing.
- e2e metrics implementation: `RU_3OPS_DISCOVERY_E2E_METRICS_IMPL`
  (`alloy`, the default, or `vmagent`; anything else is a usage error,
  `tools.backends.selected_metrics_implementation`). With `vmagent` the
  fixtures materialize Alloy without `tools.backends.METRICS_IMPL_DOMAINS`
  (`metrics` and `ipmi`, which load the same Alloy files) and add
  `tests/e2e/stack/docker-compose.vmagent.yml`, which mounts
  `implementations/vmagent/` and writes to the store named by
  `BackendSpec.metrics_write_url`. Metrics-domain checks compare
  `collector` with `Stack.collector("metrics")`, never a literal
  (`tests/static/test_backends.py` maps e2e files to domains and fails on
  an `"alloy"` literal in a vmagent domain).
- `@pytest.mark.alloy_internals` marks e2e checks that read Alloy internals
  (UI API, component graph) rather than the contract's output; they run on
  both storage variants, since Alloy is the collector in both, and are
  deselected in `e2e_vmagent` and `e2e_vmagent_victoria`, where the Alloy
  metrics pipeline they inspect is absent. Loki drops
  entries with identical timestamp and line in one stream at ingest, so a
  duplicate tailer is visible in storage only on VictoriaLogs; on Loki the
  `alloy_internals` twin is the pinned check.

## Hard rules

- The Alloy image tag is pinned BY THE MANIFEST (section 14.4, currently
  v1.21.2); `noxfile.ALLOY_IMAGE` must match - a static test enforces
  it. `foreach` (only in `030_database.alloy`, `EXPERIMENTAL_FILES`) is
  experimental: `--stability.level=experimental` is passed exactly when
  the domain set includes `database` (`needs_experimental`); alloy_check
  validates every other combo without it, so the flag cannot mask an
  experimental block elsewhere.
- Contract values (scrape intervals, label names, defaults) are never
  changed to make a test pass; e2e accelerates only
  `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL`.
- No secrets in git, not even fakes: `*.dsn` etc. are generated by
  fixtures into gitignored temp dirs. One documented exception, and it
  stays one: the SNMPv3 pair in `tests/e2e/stack/snmp-agent/snmpd.conf`
  and `tools/stack_secrets.py`. The agent reads it from a file baked
  into the image at build time while Alloy reads it from a fixture, so
  both sides need the value before either process starts and there is no
  run to generate it in. Both sites carry the reason next to the
  `detect-secrets` pragma, which would otherwise hide the breach.
- Versions of external artifacts (packages, images, hook revs) are
  pinned from live sources, never from memory.
- The label namespace is reverse-DNS (`ru.3ops.discovery.*`),
  deliberately NOT an `x-` prefix: compose treats an `x-` prefixed key
  in a `labels:` mapping as an extension and silently drops it, so a
  reverse-DNS namespace lets both the map and list label forms work.
  The e2e compose uses the map form on purpose, so the gate proves
  reverse-DNS keys survive compose parsing; the list form is equally
  valid.
- The manifest is normative in Russian; `docs/manifest.md` and the
  `*.md` twins of `README.ru.md`/`CHANGELOG.ru.md` are translations kept
  in the same commit. Code, comments, commits and other shipped markdown
  are English.
- The contract version lives only in the manifest header
  (`tests/static/test_release.py`); `ru.3ops.discovery.version` is the
  label-semantics version and moves only when a label changes meaning.
- VictoriaLogs in e2e runs with `-loki.disableMessageParsing`: without it
  a JSON line pushed over the Loki API is unpacked into fields and `_msg`
  no longer holds the line, so the structured-metadata checks would pass
  on fields the store made up rather than on what Alloy sent.
- VictoriaMetrics in e2e runs with `-search.latencyOffset=1s`: the default
  30s offset hides fresh samples from queries for 30s, longer than the
  delivery budgets allow.
- Conventional Commits; no AI-attribution trailers.
