"""Multi-type database exporter delivery (manifest 5.3, 6.1 provenance)."""

import pytest

from tests.e2e.conftest import (
    METRICS_BUDGET,
    ReadinessTimeoutError,
    Stack,
    wait_until,
)
from tools.series_catalog import load_catalog

#: The only series family basic-v1 switches off (manifest 8.4); every other
#: series a basic-v1 exporter serves must survive on the wider profiles.
_BASIC_ONLY_DROPS = "pg_settings_"


def _up_metric(stack: Stack, family: str) -> bool:
    result = stack.prom_query(f'{family}{{compose_project="{stack.project}"}}')
    return bool(result) and float(result[0]["value"][1]) == 1.0


@pytest.mark.parametrize(
    ("family", "service"),
    [
        ("mysql_up", "mariadb"),
        ("redis_up", "redis"),
        ("mongodb_up", "mongodb"),
    ],
)
def test_exporter_authenticated(
    stack: Stack, family: str, service: str
) -> None:
    # up == 1 requires a successful connection AND authentication, not
    # merely a running exporter. Scoped to compose_project because the
    # provenance enrichment (phase 2) now attaches it to db series.
    wait_until(
        lambda: _up_metric(stack, family),
        timeout=METRICS_BUDGET,
        desc=f"{family} == 1 for {service}",
    )


@pytest.mark.parametrize(
    ("family", "db_type", "instance", "has_optional"),
    [
        # mariadb declares database.instance: the declared identity must
        # win over the synthesized secret-id fallback (manifest 5, 10.2.1).
        ("mysql_up", "mariadb", "billing-db", True),
        ("redis_up", "redis", "redis-cache", True),
        # mongodb omits environment/team labels on purpose: proves the
        # enrichment tolerates absent optional labels.
        ("mongodb_up", "mongodb", "mongodb-docs", False),
    ],
)
def test_db_series_carry_provenance(
    stack: Stack,
    family: str,
    db_type: str,
    instance: str,
    has_optional: bool,
) -> None:
    # Scoped by instance: a db type can run several exporters (the
    # profile pair does exactly that for postgres), so an unscoped query
    # returns an arbitrary one. Waiting for a series with this instance
    # still proves the enriched identity: only the enrichment can
    # produce it -- the declared database.instance for mariadb, the
    # synthesized secret-id fallback for the others.
    series = wait_until(
        lambda: stack.prom_query(
            f'{family}{{compose_project="{stack.project}",'
            f'instance="{instance}"}}'
        ),
        timeout=METRICS_BUDGET,
        desc=f"{family} series present",
    )
    labels = series[0]["metric"]
    assert labels["collector"] == "alloy"
    assert labels["host"], "db series lost the manifest 6.1 host label"
    assert labels["compose_project"] == stack.project
    assert labels["container"]
    # Enriched identity must survive prometheus.scrape's defaults
    # (scrape would otherwise set job to its own component name).
    assert labels["job"] == db_type
    assert labels["instance"] == instance
    if has_optional:
        assert labels["environment"] == "e2e"
        assert labels["team"] == "data"
    else:
        # coalesce(absent, "") -> "" -> relabel drops the empty label.
        assert "environment" not in labels
        assert "team" not in labels


def test_extended_profile_enables_extra_collectors(stack: Stack) -> None:
    # The postgres service declares database.profile=extended-v1.
    # pg_long_running_transactions comes from the long_running_transactions
    # collector, which only that profile enables, so its presence pins the
    # label to a real change in collection scope (pg_up alone cannot:
    # every profile emits it).
    series = wait_until(
        lambda: stack.prom_query(
            "pg_long_running_transactions"
            f'{{compose_project="{stack.project}"}}'
        ),
        timeout=METRICS_BUDGET,
        desc="extended-only postgres collector metric present",
    )
    assert series[0]["metric"]["instance"] == "postgres-orders"


def test_basic_profile_shrinks_collection(stack: Stack) -> None:
    # postgres-basic declares basic-v1 (disable_settings_metrics): the
    # exporter must stay authenticated and up, yet stop exposing the
    # pg_settings series. postgres-orders (extended-v1, settings stay
    # on) is the positive control proving the absence comes from the
    # profile, not from a change in exporter behaviour. The settings
    # series ship in the same scrape as pg_up, so once both anchors are
    # visible the absence check cannot race the remote_write path.
    def _pg_up(instance: str) -> bool:
        result = stack.prom_query(
            f'pg_up{{compose_project="{stack.project}",instance="{instance}"}}'
        )
        return bool(result) and float(result[0]["value"][1]) == 1.0

    wait_until(
        lambda: _pg_up("postgres-audit"),
        timeout=METRICS_BUDGET,
        desc="basic-v1 postgres exporter up",
    )
    wait_until(
        lambda: stack.prom_query(
            f'pg_settings_max_connections{{compose_project="{stack.project}",'
            'instance="postgres-orders"}'
        ),
        timeout=METRICS_BUDGET,
        desc="control profile keeps the pg_settings series",
    )
    assert not stack.prom_query(
        f'pg_settings_max_connections{{compose_project="{stack.project}",'
        'instance="postgres-audit"}'
    )


def test_extended_profile_keeps_the_standard_set(stack: Stack) -> None:
    # Profiles are monotonic (manifest 8.4): extended-v1 adds collectors on
    # top of the default set, it must not replace it. Every catalog series
    # of postgres/basic-v1 except the pg_settings family it drops has to
    # reach storage from the extended-v1 service too. Polled rather than
    # checked once: an anchor series of the same scrape being visible does
    # not make its siblings visible in the same instant query.
    basic = load_catalog()["database", "postgres/basic-v1"]
    expected = {
        name
        for name in basic.present
        if not name.startswith(_BASIC_ONLY_DROPS)
    }
    scope = f'compose_project="{stack.project}",compose_service="postgres"'
    names = "|".join(sorted(expected))
    missing = set(expected)

    def _all_served() -> bool:
        served = {
            series["metric"]["__name__"]
            for series in stack.prom_query(f'{{__name__=~"{names}",{scope}}}')
        }
        missing.clear()
        missing.update(expected - served)
        return not missing

    try:
        wait_until(
            _all_served,
            timeout=METRICS_BUDGET,
            desc="extended-v1 serves the basic-v1 series",
        )
    except ReadinessTimeoutError:
        pytest.fail(f"extended-v1 lacks basic-v1 series: {sorted(missing)}")


def test_mongodb_standard_profile_serves_server_status(stack: Stack) -> None:
    # standard-v1 is full collection (manifest 8.4) from the first scrape
    # on: every series of the catalog cell must share the timestamp of the
    # earliest mongodb_up == 1 sample. The exporter widens collect_all
    # only while serving its first scrape, so relying on collect_all alone
    # leaves the first scrape of every new exporter with mongodb_up only.
    cell = load_catalog()["database", "mongodb/standard-v1"]
    scope = f'compose_project="{stack.project}",compose_service="mongodb"'
    names = "|".join(sorted(cell.present))
    # A range selector keeps __name__ and the sample timestamps; the window
    # outlasts any e2e session, so it reaches back to the first scrape.
    expr = f'{{__name__=~"{names}",{scope}}}[6h]'
    missing = set(cell.present)

    def _all_served() -> bool:
        served = {s["metric"]["__name__"] for s in stack.prom_query(expr)}
        missing.clear()
        missing.update(cell.present - served)
        return not missing

    try:
        wait_until(
            _all_served,
            timeout=METRICS_BUDGET,
            desc="mongodb standard-v1 serves the catalog series",
        )
    except ReadinessTimeoutError:
        pytest.fail(f"mongodb standard-v1 lacks series: {sorted(missing)}")

    earliest: dict[str, float] = {}
    first_up = float("inf")
    for series in stack.prom_query(expr):
        name = series["metric"]["__name__"]
        stamps = [float(ts) for ts, _ in series["values"]]
        earliest[name] = min([earliest.get(name, stamps[0]), *stamps])
        if name == "mongodb_up":
            ups = [float(ts) for ts, v in series["values"] if float(v) == 1.0]
            first_up = min([first_up, *ups])
    late = sorted(name for name, ts in earliest.items() if ts > first_up)
    assert not late, f"missing from the first mongodb scrape: {late}"
