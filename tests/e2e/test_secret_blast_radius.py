"""
What one untrusted secret-id can take down.

`secret-id` arrives from a Docker label, so a container decides which
file the collector opens. Section 9 says what happens when that file is
absent, and this is the reproduction behind the sentence.

The blast radius is the whole `foreach` block of that database type --
not the single child pipeline, as a reading of "one local.file per
iteration" suggests. The bad iteration fails the block's evaluation and
the legitimate databases of the same type go down with it. Other types,
in their own blocks, keep collecting.

Asserted on the component graph rather than on metrics: an instant query
keeps returning the last sample for the whole staleness window, so
`mongodb_up == 1` still answers for minutes after collection has
actually stopped. Health changes immediately.

The check is destructive, so the container behind it is compose-profiled
and this module owns its lifetime: the fixture removes it even when the
assertions fail, or the mongodb coverage of every other test would
quietly vanish.
"""

import subprocess

from tests.e2e.conftest import METRICS_BUDGET, Stack, wait_until

_SERVICE = "db-nosecret"
#: The database type db-nosecret declares, and so the block it takes out.
_VICTIM = "mongodb"
#: Types living in other foreach blocks, which must survive untouched.
_BYSTANDERS = ("postgres", "mysql")


def _compose(stack: Stack, *args: str) -> None:
    subprocess.run(
        [*stack.compose_cmd, *args],
        env=stack.env,
        capture_output=True,
        text=True,
        check=True,
    )


def _block_health(stack: Stack) -> dict[str, str]:
    """
    Foreach block -> its health state.

    The children of a foreach live in a module, and the components
    endpoint lists top-level components only -- so the block is the
    finest granularity the collector actually exposes. That is also the
    granularity the failure has, which is the point of the test.
    """
    return {
        component["localID"]: component.get("health", {}).get("state", "")
        for component in stack.alloy_components()
        if component.get("localID", "").startswith("foreach.")
    }


def test_a_missing_secret_takes_down_its_whole_database_type(
    stack: Stack,
) -> None:
    # Positive control before the damage: the exporters that must
    # disappear, and the ones that must not, are alive to begin with.
    before = _block_health(stack)
    for kind in (_VICTIM, *_BYSTANDERS):
        assert before.get(f"foreach.{kind}") == "healthy", (
            f"the {kind} block is not healthy before the test: {before}"
        )

    _compose(stack, "--profile", "nosecret", "up", "-d", _SERVICE)
    try:
        unhealthy = wait_until(
            lambda: [
                component
                for component in stack.alloy_components()
                if component.get("health", {}).get("state") == "unhealthy"
            ],
            METRICS_BUDGET,
            "the foreach block of the missing secret reports unhealthy",
        )
        blocks = {component.get("localID", "") for component in unhealthy}
        assert f"foreach.{_VICTIM}" in blocks, (
            f"expected the {_VICTIM} foreach block to fail, "
            f"got {sorted(blocks)}"
        )
        message = next(
            component["health"]["message"]
            for component in unhealthy
            if component.get("localID") == f"foreach.{_VICTIM}"
        )
        assert f"{_VICTIM}-missing.dsn" in message, message

        # The radius, both halves. Everything the failed block owned goes
        # with it -- the legitimate database of the same type included,
        # since its exporter is a child of that block ...
        after = _block_health(stack)
        assert after[f"foreach.{_VICTIM}"] == "unhealthy"
        # ... and the other types are untouched, which is what makes this
        # a bounded failure rather than a collector-wide one.
        for kind in _BYSTANDERS:
            assert after.get(f"foreach.{kind}") == "healthy", (
                f"the {kind} block changed state: the failure crossed its "
                f"own foreach block ({after})"
            )
    finally:
        _compose(stack, "rm", "-sf", _SERVICE)

    # And the damage is reversible: removing the container restores the
    # block, so a later test does not inherit a dead mongodb domain.
    wait_until(
        lambda: (
            _block_health(stack).get(f"foreach.{_VICTIM}") == "healthy" or None
        ),
        METRICS_BUDGET,
        f"the {_VICTIM} block recovers once the bad container is gone",
    )
