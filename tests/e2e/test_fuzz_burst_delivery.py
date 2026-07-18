"""Fuzz resilience and burst smoke."""

import json

from tests.e2e.conftest import (
    LOGS_BUDGET,
    METRICS_BUDGET,
    Stack,
    wait_until,
)

BURST_TOTAL = 10_000  # APP_BURST=1000:10 in the compose file


def test_fuzz_markers_survive_garbage(stack: Stack) -> None:
    base = f'{{service_name="app-fuzz",compose_project="{stack.project}"}}'
    markers = wait_until(
        lambda: (
            m
            if len(m := stack.loki_entries(base + ' |= "fuzz-marker"')) >= 2
            else None
        ),
        timeout=LOGS_BUDGET * 2,
        desc="marker lines around garbage delivered",
    )
    numbers = [json.loads(line)["marker"] for _ts, line in markers]
    assert numbers == sorted(numbers)


def test_fuzz_valid_unicode_preserved(stack: Stack) -> None:
    emoji = chr(0x1F600)
    entries = wait_until(
        lambda: stack.loki_entries(
            f'{{service_name="app-fuzz",'
            f'compose_project="{stack.project}"}} |= "{emoji}"'
        ),
        timeout=LOGS_BUDGET,
        desc="emoji line delivered intact",
    )
    assert entries


def test_alloy_stays_healthy_under_fuzz(stack: Stack) -> None:
    unhealthy = [
        c
        for c in stack.alloy_components()
        if isinstance(c.get("health"), dict)
        and c["health"].get("state") == "unhealthy"
    ]
    assert not unhealthy


def test_fuzz_gauge_extremes_delivered_exactly(stack: Stack) -> None:
    expr = (
        f'app_fuzz_gauge{{job="app-fuzz",compose_project="{stack.project}"}}'
    )

    def _extreme_values() -> set[float] | None:
        # One scrape carries all three variants at once (same endpoint);
        # the extremes are fixed per variant (variant i -> extreme i), so
        # the instant sample is exact -- no fragile [range:] subquery,
        # which is empty until enough points accumulate.
        vals = {float(s["value"][1]) for s in stack.prom_query(expr)}
        return vals if (-1e300 in vals or 1e300 in vals) else None

    values = wait_until(
        _extreme_values,
        timeout=METRICS_BUDGET,
        desc="fuzz gauge extremes scraped exactly",
    )
    assert -1e300 in values or 1e300 in values
    # Unicode label values arrive undamaged.
    variants = {s["metric"]["variant"] for s in stack.prom_query(expr)}
    assert any(chr(0x1F680) in v for v in variants)


def test_burst_no_loss(stack: Stack) -> None:
    base = (
        f'{{service_name="app-burst",'
        f'compose_project="{stack.project}"}} |= "\\"event\\": \\"burst\\""'
    )

    def _all_delivered() -> list[int] | None:
        seqs = sorted(
            json.loads(line)["seq"]
            for _ts, line in stack.loki_entries(base)
            if json.loads(line).get("event") == "burst"
        )
        return seqs if len(seqs) >= BURST_TOTAL else None

    seqs = wait_until(
        _all_delivered,
        timeout=LOGS_BUDGET * 3,
        desc=f"all {BURST_TOTAL} burst lines in Loki",
        interval=5.0,
    )
    assert seqs == list(range(BURST_TOTAL)), (
        "burst lines lost or duplicated: "
        f"count={len(seqs)}, first={seqs[:3]}, last={seqs[-3:]}"
    )
