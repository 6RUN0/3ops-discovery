"""Demo sandbox guards: grafana is demo-profiled, datasources provisioned."""

import re
from pathlib import Path

import yaml
from noxfile import DEMO_COMPOSE_FILES, DEMO_EXCLUDED_DOMAINS, demo_domains

from tools.materialize import COMBOS, files_for

_STACK = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "stack"
_COMPOSE = _STACK / "docker-compose.yml"
_JOURNAL_HOST_OVERLAY = _STACK / "docker-compose.journal-host.yml"
_DATASOURCES = (
    _STACK / "grafana" / "provisioning" / "datasources" / "datasources.yaml"
)


def _grafana_block() -> str:
    text = _COMPOSE.read_text("utf-8")
    # From the grafana service header to the next top-level (2-space) service.
    m = re.search(r"(?ms)^  grafana:\n(.*?)(?=^  \w|\Z)", text)
    assert m, "grafana service not found in compose"
    return m.group(1)


def test_grafana_is_demo_profiled() -> None:
    # Without the demo profile the e2e stack would start grafana on every
    # run; the profile keeps it opt-in.
    assert 'profiles: ["demo"]' in _grafana_block()


def test_grafana_image_is_pinned() -> None:
    assert "image: grafana/grafana:13.1.1" in _grafana_block()


def test_datasources_wire_both_backends() -> None:
    text = _DATASOURCES.read_text("utf-8")
    assert "url: http://prometheus:9090" in text
    assert "url: http://loki:3100" in text


def test_anonymous_grafana_cannot_manage_datasources() -> None:
    # The same compose file is the e2e harness AND the sandbox `nox -s
    # demo` hands to a reader as an example. Managing data sources is
    # Admin-only in Grafana OSS, so an anonymous Admin could add one
    # pointing at any URL and read the answer -- an SSRF foothold inside
    # the telemetry network, reached with no credentials at all.
    role = re.search(r"GF_AUTH_ANONYMOUS_ORG_ROLE=(\w+)", _grafana_block())
    assert role, "anonymous org role not set on the demo grafana"
    assert role.group(1) != "Admin"


def test_the_alloy_api_is_not_published_beyond_loopback() -> None:
    # Inside the telemetry network the unauthenticated HTTP server is
    # reachable by every workload and cannot be made otherwise -- a
    # collector shares a network with what it scrapes (manifest 13.3).
    # The host boundary is the one that IS enforceable, so it is the one
    # pinned here: loopback, ephemeral port, never 0.0.0.0.
    files = sorted(_STACK.glob("docker-compose*.yml"))
    assert _STACK / "docker-compose.victoria.yml" in files
    published = [
        (path.name, mapping)
        for path in files
        for mapping in re.findall(
            r'^\s*- "([^"]*:\d+|\d+):\d+"',
            path.read_text("utf-8"),
            re.MULTILINE,
        )
    ]
    names = {name for name, _ in published}
    assert {"docker-compose.yml", "docker-compose.victoria.yml"} <= names
    for name, mapping in published:
        assert mapping.startswith("127.0.0.1:"), (
            f"{name}: port {mapping} is published beyond loopback"
        )


def _rw_cgroup_mounts(path: Path) -> list[str]:
    """Return services of a compose file mounting /sys/fs/cgroup writable."""
    doc = yaml.safe_load(path.read_text("utf-8"))
    found = []
    for name, service in (doc.get("services") or {}).items():
        for volume in service.get("volumes") or []:
            if isinstance(volume, dict):
                target = volume.get("target")
                writable = not volume.get("read_only", False)
            else:
                parts = volume.split(":")
                target = parts[1] if len(parts) > 1 else parts[0]
                modes = parts[2].split(",") if len(parts) > 2 else []
                writable = "ro" not in modes
            if target == "/sys/fs/cgroup" and writable:
                found.append(name)
    return found


def test_demo_never_mounts_the_host_cgroup_tree_writable() -> None:
    # A writable /sys/fs/cgroup lets a container write to the host cgroup
    # tree. The e2e stack is torn down within minutes; the demo runs for
    # hours on a developer machine, so journal-host stays out of it.
    # Positive control: the overlay really carries the mount this gate
    # looks for, so the check below cannot pass by parsing nothing.
    assert _rw_cgroup_mounts(_JOURNAL_HOST_OVERLAY) == ["journal-host"]
    assert _JOURNAL_HOST_OVERLAY not in DEMO_COMPOSE_FILES
    for path in DEMO_COMPOSE_FILES:
        assert _rw_cgroup_mounts(path) == [], (
            f"{path.name}: demo compose mounts /sys/fs/cgroup writable"
        )


def test_demo_does_not_load_host_logs_without_a_journal() -> None:
    # host-logs reads the journal only the e2e journal-host overlay
    # provides; the control proves the demo's source combination does
    # contain host-logs, so its absence below is the exclusion.
    assert DEMO_EXCLUDED_DOMAINS == ("host-logs",)
    assert "host-logs" in COMBOS["all-snmp"]
    assert "host-logs" not in demo_domains()
    assert "080_host-logs.alloy" not in files_for(demo_domains())
    assert "snmp" in demo_domains()
