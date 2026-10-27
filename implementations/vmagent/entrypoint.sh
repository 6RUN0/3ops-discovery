#!/bin/sh
# Applies the manifest 14.1 defaults of the metrics domain, then runs
# vmagent. vmagent leaves an unset %{NAME} placeholder in scrape.yml as
# literal text, so every variable it reads gets its default here.
set -eu

export RU_3OPS_DISCOVERY_DOCKER_HOST="${RU_3OPS_DISCOVERY_DOCKER_HOST:-unix:///var/run/docker.sock}"
export RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL="${RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL:-30s}"
export RU_3OPS_DISCOVERY_REMOTE_WRITE_URL="${RU_3OPS_DISCOVERY_REMOTE_WRITE_URL:-http://prometheus:9090/api/v1/write}"
# ":-" and not "-": an empty value also means the collector's hostname.
# Assigned apart from export: export would mask a failing hostname.
RU_3OPS_DISCOVERY_HOSTNAME="${RU_3OPS_DISCOVERY_HOSTNAME:-$(hostname)}" || {
  echo "entrypoint: hostname failed, the host label has no value" >&2
  exit 1
}
if [ -z "$RU_3OPS_DISCOVERY_HOSTNAME" ]; then
  echo "entrypoint: hostname is empty, the host label has no value" >&2
  exit 1
fi
export RU_3OPS_DISCOVERY_HOSTNAME

# vmagent docker SD dials unix:// and http(s):// only; Docker's plain
# tcp:// address is the same endpoint over http.
case "$RU_3OPS_DISCOVERY_DOCKER_HOST" in
  tcp://*)
    RU_3OPS_DISCOVERY_DOCKER_HOST="http://${RU_3OPS_DISCOVERY_DOCKER_HOST#tcp://}"
    ;;
esac

config_dir=$(dirname "$0")

# docker_sd_configs has no refresh_interval field: the interval is a flag.
exec /vmagent-prod \
  -promscrape.config="$config_dir/scrape.yml" \
  -promscrape.dockerSDCheckInterval="$RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL" \
  -remoteWrite.url="$RU_3OPS_DISCOVERY_REMOTE_WRITE_URL" \
  "$@"
