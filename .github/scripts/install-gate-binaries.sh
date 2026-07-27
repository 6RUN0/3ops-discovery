#!/usr/bin/env bash
# Install the system binaries the nox gate sessions expect on PATH.
#
# Versions mirror the environment the gates are known to pass with
# (behaviour drifts between linter versions, so CI must not float);
# binary downloads are checksum-pinned. Bump versions here and in the
# checksums together, from the upstream releases.
#
# Usage: install-gate-binaries.sh <tool>... where tool is one of
# hadolint, taplo, lychee, rumdl, typos.
set -euo pipefail

HADOLINT_VERSION=2.14.0
HADOLINT_SHA256=6bf226944684f56c84dd014e8b979d27425c0148f61b3bd99bcc6f39e9dc5a47
TAPLO_VERSION=0.10.0
TAPLO_SHA256=8fe196b894ccf9072f98d4e1013a180306e17d244830b03986ee5e8eabeb6156
LYCHEE_VERSION=0.24.2
LYCHEE_SHA256=1f4e0ef7f6554a6ed33dd7ac144fb2e1bbed98598e7af973042fc5cd43951c9a
RUMDL_VERSION=0.2.34
TYPOS_VERSION=1.48.0

bin_dir="${RUNNER_TEMP:-/tmp}/gate-bin"
mkdir -p "$bin_dir"
# PATH additions apply to SUBSEQUENT workflow steps, which is where the
# nox sessions run. uv tool shims land in ~/.local/bin.
echo "$bin_dir" >>"${GITHUB_PATH:?}"
echo "$HOME/.local/bin" >>"${GITHUB_PATH:?}"

fetch() { # url dest sha256
	curl -sSfL --retry 3 "$1" -o "$2"
	echo "$3  $2" | sha256sum -c --quiet
}

for tool in "$@"; do
	case "$tool" in
	hadolint)
		fetch "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-linux-x86_64" \
			"$bin_dir/hadolint" "$HADOLINT_SHA256"
		chmod +x "$bin_dir/hadolint"
		;;
	taplo)
		fetch "https://github.com/tamasfe/taplo/releases/download/${TAPLO_VERSION}/taplo-linux-x86_64.gz" \
			"$bin_dir/taplo.gz" "$TAPLO_SHA256"
		gunzip -f "$bin_dir/taplo.gz"
		chmod +x "$bin_dir/taplo"
		;;
	lychee)
		fetch "https://github.com/lycheeverse/lychee/releases/download/lychee-v${LYCHEE_VERSION}/lychee-x86_64-unknown-linux-gnu.tar.gz" \
			"$bin_dir/lychee.tar.gz" "$LYCHEE_SHA256"
		tar -xzf "$bin_dir/lychee.tar.gz" -C "$bin_dir" --strip-components=1 \
			"lychee-x86_64-unknown-linux-gnu/lychee"
		;;
	rumdl)
		uv tool install "rumdl==${RUMDL_VERSION}"
		;;
	typos)
		uv tool install "typos==${TYPOS_VERSION}"
		;;
	*)
		echo "unknown tool: $tool" >&2
		exit 1
		;;
	esac
	echo "installed $tool"
done
