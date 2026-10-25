"""Demo sandbox guards: grafana is demo-profiled, datasources provisioned."""

import re
from pathlib import Path

_STACK = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "stack"
_COMPOSE = _STACK / "docker-compose.yml"
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
