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
