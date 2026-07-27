"""SNMPv3 authPriv delivery through 037_snmp.alloy (manifest 10.6)."""

from typing import Any

from tests.e2e.conftest import METRICS_BUDGET, Stack, wait_until


def _snmp_series(snmp_stack: Stack) -> list[dict[str, Any]] | None:
    # ifNumber is served by IF-MIB out of the box; scoped to the snmp job.
    expr = 'ifNumber{job="snmp"}'
    result = snmp_stack.prom_query(expr)
    return result or None


def test_snmp_v3_delivery_with_provenance(snmp_stack: Stack) -> None:
    series = wait_until(
        lambda: _snmp_series(snmp_stack),
        timeout=METRICS_BUDGET,
        desc="ifNumber{job=snmp} delivered",
    )
    labels = series[0]["metric"]
    assert labels["job"] == "snmp"
    assert labels["instance"] == "snmp-agent:161"
    assert labels["module"] == "if_mib"  # M1: restored in enrich_snmp
    assert labels["environment"] == "e2e"
    assert labels["team"] == "platform"
    assert labels["collector"] == "alloy"
    assert labels["host"]  # constants.hostname, non-empty


def test_system_module_delivers_device_identity(snmp_stack: Stack) -> None:
    # The second device row points the system module at the same agent:
    # sysUpTime (a plain gauge from the 1.3.6.1.2.1.1 walk) only exists in
    # that module, so its presence pins the allowlist extension to a real
    # walk, not just a surviving target.
    series = wait_until(
        lambda: snmp_stack.prom_query('sysUpTime{job="snmp",module="system"}'),
        timeout=METRICS_BUDGET,
        desc="sysUpTime{module=system} delivered",
    )
    assert series[0]["metric"]["instance"] == "snmp-agent:161"


def test_valid_devices_are_kept_and_invalid_dropped(snmp_stack: Stack) -> None:
    # Fail-closed control: the fixture provisions three devices, one with a
    # module outside the (if_mib|system) allowlist. Exactly the two valid e2e
    # devices survive the relabel keep-rules; the bad-module row is dropped.
    wait_until(
        lambda: _snmp_series(snmp_stack),
        timeout=METRICS_BUDGET,
        desc="snmp pipeline alive",
    )
    kept = snmp_stack.relabel_targets_by_env("discovery.relabel.snmp", "e2e")
    assert kept == 2, (
        f"expected exactly the two valid e2e devices kept, got {kept}"
    )
