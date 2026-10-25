"""The stack comes up healthy and Alloy loads the full config."""

import pytest

from tests.e2e.conftest import Stack


def _health_state(component: dict[str, object]) -> object:
    health = component.get("health")
    return health.get("state") if isinstance(health, dict) else None


@pytest.mark.alloy_internals
def test_alloy_components_are_healthy(stack: Stack) -> None:
    components = stack.alloy_components()
    assert components, "Alloy reported no components"
    unhealthy = [
        c for c in components if _health_state(c) not in ("healthy", "unknown")
    ]
    assert not unhealthy, f"unhealthy components: {unhealthy}"
