"""Multi-type database exporter delivery (manifest 5.3, 6.1 provenance)."""

import pytest

from tests.e2e.conftest import METRICS_BUDGET, Stack, wait_until


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
    ("family", "db_type", "secret_id", "has_optional"),
    [
        ("mysql_up", "mariadb", "mariadb-billing", True),
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
    secret_id: str,
    has_optional: bool,
) -> None:
    series = wait_until(
        lambda: stack.prom_query(
            f'{family}{{compose_project="{stack.project}"}}'
        ),
        timeout=METRICS_BUDGET,
        desc=f"{family} series present",
    )
    labels = series[0]["metric"]
    assert labels["collector"] == "alloy"
    assert labels["compose_project"] == stack.project
    assert labels["container"]
    # Synthesised identity must survive prometheus.scrape's defaults
    # (scrape would otherwise set job to its own component name).
    assert labels["job"] == db_type
    assert labels["instance"] == secret_id
    if has_optional:
        assert labels["environment"] == "e2e"
        assert labels["team"] == "data"
    else:
        # coalesce(absent, "") -> "" -> relabel drops the empty label.
        assert "environment" not in labels
        assert "team" not in labels
