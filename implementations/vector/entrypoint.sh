#!/bin/sh
# Applies the manifest 14.1 defaults of the logs domain, then runs Vector.
# vector.yaml reads ${NAME} interpolations, which Vector expands only with
# --dangerously-allow-env-var-interpolation; every one is set here.
set -eu

export RU_3OPS_DISCOVERY_DOCKER_HOST="${RU_3OPS_DISCOVERY_DOCKER_HOST:-unix:///var/run/docker.sock}"
export RU_3OPS_DISCOVERY_LOKI_PUSH_URL="${RU_3OPS_DISCOVERY_LOKI_PUSH_URL:-http://loki:3100/loki/api/v1/push}"
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

# A newline in an interpolated value could add YAML keys to the config,
# and the hostname, read by VRL, would become a broken label value.
newline='
'
reject_newline() {
  case "$2" in
    *"$newline"*)
      echo "entrypoint: $1 contains a newline" >&2
      exit 1
      ;;
  esac
}
reject_newline RU_3OPS_DISCOVERY_DOCKER_HOST "$RU_3OPS_DISCOVERY_DOCKER_HOST"
reject_newline RU_3OPS_DISCOVERY_LOKI_PUSH_URL "$RU_3OPS_DISCOVERY_LOKI_PUSH_URL"
reject_newline RU_3OPS_DISCOVERY_HOSTNAME "$RU_3OPS_DISCOVERY_HOSTNAME"

# The loki sink always joins endpoint + "/" + path, so the push URL is
# split at its last slash. A query or fragment would be split inside it
# and the sink's path would carry it, so such a URL is refused.
case "$RU_3OPS_DISCOVERY_LOKI_PUSH_URL" in
  *[?#]*)
    echo "entrypoint: RU_3OPS_DISCOVERY_LOKI_PUSH_URL with a query or fragment is not supported" >&2
    exit 1
    ;;
esac
case "${RU_3OPS_DISCOVERY_LOKI_PUSH_URL#*://}" in
  */*[!/]) ;;
  *)
    echo "entrypoint: RU_3OPS_DISCOVERY_LOKI_PUSH_URL needs a path that does not end in /" >&2
    exit 1
    ;;
esac
export DISCOVERY_LOKI_ENDPOINT="${RU_3OPS_DISCOVERY_LOKI_PUSH_URL%/*}"
export DISCOVERY_LOKI_PATH="${RU_3OPS_DISCOVERY_LOKI_PUSH_URL##*/}"

VECTOR_CONFIG="$(dirname "$0")/vector.yaml"
export VECTOR_CONFIG

exec vector --dangerously-allow-env-var-interpolation "$@"
