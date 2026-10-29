"""Compose stack guards for runner kernels the dev host does not have."""

import re
from pathlib import Path
from typing import Any

import yaml

_STACK = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "stack"
#: mongo 8 and newer: SERVER-121912 affects every 8.x release.
_MONGO_8_PLUS = re.compile(r"^mongo:(?:[89]|\d{2,})\.")


def _services() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for compose in sorted(_STACK.glob("docker-compose*.yml")):
        data = yaml.safe_load(compose.read_text("utf-8")) or {}
        for name, service in (data.get("services") or {}).items():
            found[f"{compose.name}:{name}"] = service or {}
    return found


def test_mongo_8_keeps_rseq_for_glibc() -> None:
    """Pins the rseq tunable that lets mongod 8 start on Linux 6.19+."""
    # On kernels 6.19 to 7.0.13 mongod 8 exits at once with "Linux kernel
    # versions 6.19 and newer has a known incompatibility"
    # (SERVER-121912), so every e2e cell fails on `compose up`. GitHub
    # runners have such a kernel, the dev host may not, so only this gate
    # sees the regression before CI does.
    mongo = {
        name: service
        for name, service in _services().items()
        if _MONGO_8_PLUS.match(str(service.get("image", "")))
    }
    assert mongo, "no mongo 8+ service found; drop this gate with it"
    for name, service in mongo.items():
        env = service.get("environment") or {}
        assert isinstance(env, dict), f"{name}: use the map form"
        assert env.get("GLIBC_TUNABLES") == "glibc.pthread.rseq=1", name
