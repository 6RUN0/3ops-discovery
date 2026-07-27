"""Blackbox probe delivery (manifest 10.4)."""

from typing import Any

from tests.e2e.conftest import METRICS_BUDGET, Stack, wait_until

#: module -> compose service its probe targets. Service names deliberately
#: avoid sharing a substring so per-container assertions cannot collide.
_MODULE_SERVICES = {
    "http_2xx": "blackbox-probe",
    "tcp_connect": "probe-tcp",
    "icmp": "probe-icmp",
}


def _probe_success(stack: Stack, module: str) -> list[dict[str, Any]] | None:
    # Return the module's probe_success series once it reaches 1, else None
    # so wait_until keeps polling. The `module` label is promoted by the
    # enrich step in 035 (__param_module alone is dropped at scrape time),
    # so it doubles as the per-probe-type discriminator the operator gets.
    expr = (
        f'probe_success{{module="{module}",compose_project="{stack.project}"}}'
    )
    result = stack.prom_query(expr)
    if result and float(result[0]["value"][1]) == 1.0:
        return result
    return None


def test_probe_success_delivered_per_module(stack: Stack) -> None:
    # Alloy probes one container per shipped module and remote-writes
    # probe_success. The instance shape pins the per-module target
    # composition end-to-end: http gets a URL, tcp host:port, icmp a bare
    # host (a port there would break the icmp prober's name resolution).
    for module, service in _MODULE_SERVICES.items():

        def _delivered(
            module: str = module,
        ) -> list[dict[str, Any]] | None:
            return _probe_success(stack, module)

        series = wait_until(
            _delivered,
            timeout=METRICS_BUDGET,
            desc=f"probe_success == 1 for {module}",
        )
        labels = series[0]["metric"]
        assert labels["job"] == "blackbox"
        assert labels["environment"] == "e2e"
        assert labels["team"] == "platform"
        assert labels["collector"] == "alloy"
        assert labels["host"]
        assert labels["container"] == stack.compose_container(service)
        instance = labels["instance"]
        if module == "http_2xx":
            assert instance.endswith(":8080/metrics")
        elif module == "tcp_connect":
            assert instance.endswith(":8080")
            assert "://" not in instance
        else:  # icmp: bare container IP, no scheme, no port
            assert "://" not in instance
            assert ":" not in instance


def test_only_valid_probe_targets_survive_the_shared_relabel(
    stack: Stack,
) -> None:
    # Fail-closed gates observed by NAME, not by count: blackbox-badscheme
    # must be dropped by the scheme keep-rule (manifest 11) and
    # probe-badmodule by the module allowlist (manifest 10.4). Asserting
    # the exact surviving set makes each drop attributable and turns a
    # vanished valid target (e.g. probe-icmp losing its exposed port and
    # failing the keepequal) into a missing name instead of a
    # coincidentally-right count.
    expected = {
        "/" + stack.compose_container(service)
        for service in _MODULE_SERVICES.values()
    }

    def _names() -> set[str]:
        return {
            t.get("__meta_docker_container_name", "")
            for t in stack.relabel_target_labels("discovery.relabel.blackbox")
        }

    wait_until(
        lambda: _names() == expected,
        timeout=METRICS_BUDGET,
        desc="exact valid-probe set on the shared blackbox relabel",
    )
    assert _names() == expected


def test_fast_profile_probe_is_routed_to_fast_pair(stack: Stack) -> None:
    # Manifest 8.2 routing across the exporter: probe-tcp declares fast-v1;
    # the raw profile label must survive prometheus.exporter.blackbox up to
    # the enrich output and route the target into the fast filter ONLY.
    # The normal filter's "(normal-v1)?" regex accepts the empty value, so
    # a profile label lost inside the exporter would silently reroute the
    # probe to the default pair; membership on both filters exposes that.
    profile_label = (
        "__meta_docker_container_label_ru_3ops_discovery_blackbox_profile"
    )
    name_label = "__meta_docker_container_name"
    tcp = "/" + stack.compose_container("probe-tcp")

    def _enrich_sees_profile() -> bool:
        return any(
            t.get(name_label) == tcp and t.get(profile_label) == "fast-v1"
            for t in stack.relabel_target_labels(
                "discovery.relabel.enrich_blackbox"
            )
        )

    wait_until(
        _enrich_sees_profile,
        timeout=METRICS_BUDGET,
        desc="raw profile label survives the exporter",
    )
    fast = stack.relabel_target_labels("discovery.relabel.blackbox_fast_v1")
    normal = stack.relabel_target_labels(
        "discovery.relabel.blackbox_normal_v1"
    )
    assert any(t.get(name_label) == tcp for t in fast)
    assert not any(t.get(name_label) == tcp for t in normal)
