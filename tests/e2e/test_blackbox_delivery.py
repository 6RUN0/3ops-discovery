"""Blackbox probe delivery (manifest 10.4)."""

from typing import Any

from tests.e2e.conftest import METRICS_BUDGET, Stack, wait_until


def _probe_success_series(stack: Stack) -> list[dict[str, Any]] | None:
    # Return the probe_success series for this run once it reaches 1, else
    # None so wait_until keeps polling. Scoped to the run via compose_project.
    expr = f'probe_success{{compose_project="{stack.project}"}}'
    result = stack.prom_query(expr)
    if result and float(result[0]["value"][1]) == 1.0:
        return result
    return None


def test_probe_success_delivered(stack: Stack) -> None:
    # Alloy probes blackbox-probe over HTTP (module http_2xx) and remote-writes
    # probe_success.
    series = wait_until(
        lambda: _probe_success_series(stack),
        timeout=METRICS_BUDGET,
        desc="probe_success == 1",
    )
    labels = series[0]["metric"]
    assert labels["job"] == "blackbox"
    assert labels["environment"] == "e2e"
    assert labels["team"] == "platform"
    assert labels["collector"] == "alloy"
    # Target identity is the `container` passthrough label -- the full Docker
    # container name (`<project>-blackbox-probe-<index>`), matched by substring
    # exactly as test_metrics_delivery does. NOT `instance`: instance is the
    # composed probe URL `http://<container-ip>:8080/metrics` (host is
    # __meta_docker_network_ip, a numeric IP, so it carries no container name).
    assert "blackbox-probe" in labels["container"]
    assert labels["instance"].endswith(":8080/metrics")


def test_invalid_scheme_target_is_dropped(stack: Stack) -> None:
    # Negative gate (manifest 11): blackbox-badscheme declares scheme "ftp";
    # the scheme keep-rule (regex "(https?)?") must drop it. Assert on the
    # relabel output SIZE scoped to this project -- a dropped target emits no
    # series, so a label assertion could not observe it (same technique as
    # test_badsecret_target_is_dropped in 030).
    # Positive control first: the valid probe pipeline is alive, so a kept
    # count of one is evidence of the drop, not of a broken blackbox domain.
    wait_until(
        lambda: _probe_success_series(stack),
        timeout=METRICS_BUDGET,
        desc="valid probe pipeline alive",
    )
    kept = stack.relabel_project_targets("discovery.relabel.blackbox")
    assert kept == 1, (
        f"expected only the valid probe target after the invalid-scheme "
        f"drop, got {kept} (scheme allowlist not fail-closed?)"
    )
