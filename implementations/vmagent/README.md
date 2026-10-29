# vmagent implementation

A second implementation of the `metrics` domain of the 3ops Discovery
contract, on VictoriaMetrics vmagent. The manifest section
[14](../../docs/manifest.md#14-implementations) registers it for `metrics`
and `ipmi` (an ipmi exporter is scraped as an ordinary metrics target,
manifest 10.7) and pins its image tag; this file explains how the
configuration is built and adds no requirement. Other domains stay with
the [Alloy reference](../alloy/README.md): one collector per domain on a
host, never two.

## Files

| File | Role |
|---|---|
| [`scrape.yml`](scrape.yml) | One `scrape_config` for the domain: Docker discovery, then the relabel rules of the reference `020_metrics.alloy`, in its order. |
| [`entrypoint.sh`](entrypoint.sh) | POSIX sh: applies the manifest 14.1 defaults of the domain and starts vmagent. |

## Running

Mount the directory and start vmagent through the entrypoint; the
image's own entrypoint would skip the defaults.

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
host (here the host's own name): manifest
[14](../../docs/manifest.md#14-implementations) requires it and names what
breaks when it is unset.

Put the unsent-data buffer (`-remoteWrite.tmpDataPath`, default
`vmagent-remotewrite-data` under the image's working directory `/`) on a
volume, as above: without one it lives in the container's writable layer,
so recreating the container loses unsent samples, and a `--read-only`
container fails at start with `cannot create directory: mkdir
vmagent-remotewrite-data: read-only file system`.

Arguments after `entrypoint.sh` are appended to the flags the entrypoint
sets, so appending `-dryRun` checks the configuration and exits. The
remote write address is the exception: the entrypoint always passes
`-remoteWrite.url` from `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL`, and
`-remoteWrite.url` is an array flag, so another `-remoteWrite.url`
argument adds a second destination instead of replacing it. Set the
address through the variable only.

```sh
docker run --rm -v "$PWD/implementations/vmagent:/etc/vmagent:ro" \
  --entrypoint /bin/sh \
  victoriametrics/vmagent:v1.154.1 /etc/vmagent/entrypoint.sh -dryRun
```

In the repository, `uv run nox -s vmagent_check` is the gate that runs
this check twice, once with no environment and once with the e2e values.

| Variable | Default | How vmagent receives it |
|---|---|---|
| `RU_3OPS_DISCOVERY_DOCKER_HOST` | `unix:///var/run/docker.sock` | `%{...}` placeholder in `docker_sd_configs.host` |
| `RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL` | `30s` | `-promscrape.dockerSDCheckInterval` flag |
| `RU_3OPS_DISCOVERY_HOSTNAME` | hostname of the vmagent container | `%{...}` placeholder in the `host` relabel rule |
| `RU_3OPS_DISCOVERY_REMOTE_WRITE_URL` | `http://prometheus:9090/api/v1/write` | `-remoteWrite.url` flag |

An empty `RU_3OPS_DISCOVERY_HOSTNAME` counts as unset. Do not embed
credentials in the remote write URL: vmagent hides the flag value in its
log, but the URL stays readable in the container environment.

## Docker API access

Give vmagent the Docker API through a GET-only proxy (manifest 13.3),
never the socket itself. Discovery reads two endpoints, so the proxy
must allow these sections:

| Section (`tecnativa/docker-socket-proxy`) | Endpoint |
|---|---|
| `CONTAINERS=1` | `GET /containers/json` |
| `NETWORKS=1` | `GET /networks` |

`POST=0` stays off; vmagent writes nothing to the Docker API.

## Push ingestion port

vmagent accepts pushed samples without authentication on its HTTP listen
port (`-httpListenAddr`, `:8429` by default): Prometheus remote_write
(`/api/v1/write`), `/api/v1/import*`, InfluxDB line protocol (`/write`)
and OTLP (`/opentelemetry/v1/metrics`), and forwards them to the remote
write address. Any container that reaches the port can write series with
any `container`, `host` and `collector` label, so the manifest 13.5
guarantee that a forged series still carries its sender's honest
`container` and `host` does not hold for pushed data. Keep the port off
networks shared with untrusted containers, or close it with
`-httpAuth.username`/`-httpAuth.password` (then the scrape of vmagent's
own `/metrics` needs the same credentials). The divergence is the
`METRICS_IMPLEMENTATION_GAPS` row of
[`tests/static/asymmetries.py`](../../tests/static/asymmetries.py).

## Differences from the reference

The contract behaviour is the same: fail-closed `metrics.port` and
`metrics.job`, the port match against the per-port fan-out of Docker
discovery, provenance labels written after every user label (so a
container label cannot set `container`, `collector` or `host`), no
redirects, and an unknown `metrics.profile` dropped rather than scraped
as `normal-v1`. The mechanics differ where vmagent differs from Alloy:

- Profiles. Alloy routes each profile to its own `prometheus.scrape`;
  vmagent has one `scrape_config`, and relabel rules set
  `__scrape_interval__` and `__scrape_timeout__` per profile from the
  manifest 8.2 table.
- Unset placeholders. vmagent leaves an unset `%{NAME}` as literal text
  and starts anyway, so the defaults live in `entrypoint.sh`, and every
  placeholder of `scrape.yml` must have a default there (a static gate
  checks it).
- Docker host scheme. vmagent dials `unix://` and `http(s)://` only;
  `entrypoint.sh` rewrites Docker's plain `tcp://host:port` to
  `http://host:port`. A TLS endpoint is given as `https://`.
- Refresh interval. `docker_sd_configs` has no `refresh_interval`
  field, so the interval is the `-promscrape.dockerSDCheckInterval`
  flag, which applies to every Docker discovery of the process.
- Network labels. vmagent sends the discovery `filters` to
  `GET /networks` as well, so the label filter leaves no network
  metadata: `__meta_docker_network_name` and its siblings are absent,
  while `__meta_docker_network_ip` comes from the container itself. The
  rules use only the IP; `asymmetries.DISCOVERY_META_LABELS_ABSENT` lists
  the absent labels, and a static gate fails if `scrape.yml` reads one.
- Multi-network containers. As in the reference, `match_first_network`
  keeps the first network by name; an unreachable choice shows up as
  `up == 0`.

Divergences the gates accept are listed with their reasons in
[`tests/static/asymmetries.py`](../../tests/static/asymmetries.py).
