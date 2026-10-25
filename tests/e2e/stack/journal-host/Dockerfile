FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

# DL3008: trixie point releases replace package versions in the archive, so a
# pinned version would stop resolving; the base digest fixes the release line.
# hadolint ignore=DL3008
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      systemd systemd-sysv \
    && rm -rf /var/lib/apt/lists/*

# tmp.mount fails without CAP_SYS_ADMIN ("mount: /tmp: permission denied")
# and would leave the system degraded instead of running.
RUN systemctl mask tmp.mount

# systemd as PID 1 ignores SIGTERM; SIGRTMIN+3 is its clean shutdown.
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
