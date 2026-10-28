# Vector implementation

A second implementation of the `logs` domain of the 3ops Discovery
contract, on Vector. The manifest section
[14](../../docs/manifest.md#14-implementations) registers it for `logs`
and pins its version; this file explains how the configuration is built
and adds no requirement. Other domains stay with the
[Alloy reference](../alloy/README.md): one collector per domain on a
host, never two.

## Files

| File | Role |
|---|---|
| [`vector.yaml`](vector.yaml) | The pipeline: `docker_logs` source, opt-out filter, stream labels in VRL, a route per log profile, the parsers, `reduce` for the multiline profiles and one `loki` sink. |
| [`entrypoint.sh`](entrypoint.sh) | POSIX sh: applies the manifest 14.1 defaults of the domain, checks them, splits the push URL and starts Vector. |

## Running

Mount the directory and start Vector through the entrypoint; the
image's own entrypoint would skip the defaults, and Vector would read
every `${NAME}` in `vector.yaml` as literal text.

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

The image is the `-alpine` variant because the entrypoint needs
`/bin/sh`; the `distroless` variants have none.

`vector.yaml` sets `data_dir: /var/lib/vector`, where Vector keeps its
working state. The volume above only keeps that directory across
container re-creation; the config stores no read positions there (see
"Lines written while Vector is down" below), and with `docker run
--read-only` and nothing mounted on it Vector 0.60.0 still starts, so
the e2e overlay mounts a tmpfs on it. A static gate keeps the overlay's
tmpfs path equal to `data_dir`.

Set `RU_3OPS_DISCOVERY_HOSTNAME` to the same value on every collector of
the host (here the host's own name): left unset, each collector reports
its own container hostname, and the domains of one machine no longer
join on `host`.

Give the container a `--hostname` (compose: `hostname:`) that is not a
prefix of its container ID. `docker_logs` skips the container whose ID
starts with Vector's own hostname, and Docker's default hostname is the
short container ID, so without it Vector does not collect its own logs,
while the reference collects every container. Collecting them makes no
loop: Vector writes no line per delivered event.

Arguments after `entrypoint.sh` go to Vector unchanged, so this checks
the configuration and exits, in the shape an archive reader can run:

```sh
docker run --rm -v "$PWD/implementations/vector:/etc/vector:ro" --entrypoint /bin/sh timberio/vector:0.60.0-alpine /etc/vector/entrypoint.sh validate --no-environment
```

In the repository, `uv run nox -s vector_check` is the gate that runs
this check twice, once with no environment and once with the e2e values,
with `--deny-warnings` added.

| Variable | Default | How Vector receives it |
|---|---|---|
| `RU_3OPS_DISCOVERY_DOCKER_HOST` | `unix:///var/run/docker.sock` | `${...}` interpolation in `docker_host`; `tcp://` works as is |
| `RU_3OPS_DISCOVERY_HOSTNAME` | hostname of the Vector container | `get_env_var` in VRL, at run time |
| `RU_3OPS_DISCOVERY_LOKI_PUSH_URL` | `http://loki:3100/loki/api/v1/push` | split by the entrypoint into the sink `endpoint` and `path` |

An empty value counts as unset. `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL`
is not read: `docker_logs` follows the Docker event stream and picks up a
new container when it starts, so there is no list to refresh. Do not
embed credentials in the push URL: the value is readable in the container
environment.

## Docker API access

Give Vector the Docker API through a GET-only proxy (manifest 13.3),
never the socket itself. `docker_logs` reads two sections:

| Section (`tecnativa/docker-socket-proxy`) | Endpoints |
|---|---|
| `CONTAINERS=1` | `GET /containers/json`, `GET /containers/<id>/json`, `GET /containers/<id>/logs` |
| `EVENTS=1` | `GET /events` |

`POST=0` stays off; Vector writes nothing to the Docker API.

## Differences from the reference

The contract behaviour is the same: every container's logs by default,
opt-out only on the literal `false` (any other value keeps collecting,
manifest 10.3.5), stream labels only from Docker metadata and container
labels and only from the 6.2 allowlist, the 8.3 profiles with their
structured metadata fields, best-effort parsing that keeps the raw line,
and an unknown or empty profile collected as `raw-v1`. The mechanics
differ where Vector differs from Alloy:

- Environment interpolation. Vector expands `${NAME}` in its config only
  with `--dangerously-allow-env-var-interpolation`, which the entrypoint
  passes. Without the flag the literal text stays, and `vector validate`
  still passes, so a static gate pins the flag in the entrypoint. With
  it, a bare `$NAME` anywhere in the file is expanded too, VRL included,
  so every literal `$` in `vector.yaml` is written `$$` (a static gate
  checks it). The values come from the operator, not from monitored
  containers. A newline in a value could add YAML keys to the config:
  Vector refuses one in an interpolated value, and the entrypoint
  refuses one in any of the three variables, the hostname included,
  which VRL reads at run time where Vector does not check it.
- Push URL. The `loki` sink always builds its address as
  `endpoint + "/" + path`, so the full URL of
  `RU_3OPS_DISCOVERY_LOKI_PUSH_URL` cannot go into `endpoint` alone: it
  would gain a second `/loki/api/v1/push`. The entrypoint splits the URL
  at its last `/` and refuses one without a path, ending in `/`, or
  carrying a query string or fragment (the split would land inside it).
- Sink healthcheck. It is off. The sink probes `<endpoint>/ready`, which
  after the split is `http://loki:3100/loki/api/v1/ready`, a 404 on Loki,
  and VictoriaLogs has no `/ready` under its Loki path at all. A failed
  healthcheck only writes an error to Vector's log and never blocks
  delivery.
- Opt-out. The reference does not open the stream of an opted-out
  container; Vector reads it and drops its lines in a filter before
  anything else, which manifest 10.3.1 allows.
- Absent labels. Stream labels are built in VRL as one object holding
  only non-empty values, and the sink expands that object whole, so a
  container without `environment`, `team` or `logs.service` gets no
  such label. A per-label template would also leave the label out, but
  with a warning per event.
- Multiline. `python-stacktrace-v1` and `java-stacktrace-v1` go through
  `reduce`, grouped by container, with the 8.3 ISO-8601 anchor,
  `max_events: 128` and `expire_after_ms: 10000`, the reference's
  `max_lines` and `max_wait_time`.
- Unknown profile. The fallback writes a warning naming the container
  and the profile to Vector's own log (manifest 10.3.4, item 3), at
  most one per minute: a second misconfigured container within that
  minute is collected as `raw-v1` but not named. VRL has no way to
  increment a metric, so item 4 is not met.
- Lines written while Vector is down are lost. `docker_logs` keeps no
  read positions: on start it reads running containers from that moment
  on, so every line a container writes while Vector is stopped or
  restarting never reaches the store. The reference stores positions and
  resumes. This falls short of the at-least-once delivery of manifest
  14.2, which allows duplicates, not loss; it is a recorded divergence of
  this implementation. A line a container wrote before Vector started
  is lost the same way, and `docker_logs` reads a container that starts
  later only from Vector's own start. Under this implementation the
  secret-redaction e2e check therefore sees only lines written after
  Vector's start: reduced coverage, not a gap in the check.
- Own logs. Collecting Vector's own container depends on `--hostname`,
  see "Running" above.
- logfmt parsing. VRL's `parse_logfmt` and `parse_key_value` read
  `err= level=warn` as `err="level=warn"`, a standalone `level` as
  `"true"` and a repeated key as an array, where the reference's
  go-logfmt gives `level=warn`, `level=""` and the last value. The
  config therefore parses logfmt with two regexes of the go-logfmt
  grammar: the longest well-formed prefix of the line, then its pairs,
  last value winning, quoted values unescaped by JSON string rules. As
  in go-logfmt, every byte from 0x00 to 0x20 separates pairs (so a tab,
  a control character or the ESC of an ANSI colour code does, while a
  Unicode space such as NBSP is part of a value), and a closing quote
  needs no separator after it. A malformed pair ends parsing and keeps
  the pairs before it, as in the reference. Measured against Alloy v1.21.2 on these lines, with equal
  structured metadata:

  | Line | Structured metadata (both) |
  |---|---|
  | `err= level=warn` | `level=warn` |
  | `time=1 level= status=5` | `level=""`, `status=5` |
  | `Changing log level to debug` | `level=""` |
  | `level=a level=b` | `level=b` |
  | `level` | `level=""` |
  | `level=info status` | `level=info`, `status=""` |
  | `request_id="x y=z" level=debug` | `request_id=x y=z`, `level=debug` |
  | `a=b=c level=info` | none |
  | `level=info a=b=c` | `level=info` |
  | `level="unterminated status=1` | none |
  | `level="a \"b\" \\ c"` | `level=a "b" \ c` |
  | `level="a<TAB>b" status=9` (raw tab in quotes) | none |
  | `level=<ESC>[32minfo<ESC>[0m status=200` (ANSI colour) | `level=""`, `status=200` |
  | `level=info<0x01>status=5` | `level=info`, `status=5` |
  | `level="a"status=5` | `level=a`, `status=5` |
  | `level=a<NBSP>status=5` | none |

  A JSON `null` gives no entry, an empty string gives an empty one, as in
  the reference. Two known differences remain. A logfmt line longer than
  64 KiB gives no fields in the reference (its line scanner stops at that
  size), while Vector parses it whole. A lone surrogate escape such as
  `level="\ud800"` gives `U+FFFD` in the reference, while Vector keeps
  the raw text `\ud800`, because its JSON unescaping refuses the escape.

Divergences the gates accept are listed with their reasons in
[`tests/static/asymmetries.py`](../../tests/static/asymmetries.py).
