"""Prometheus delivery assertions (manifest 6.1 provenance, 14 dogfooding)."""

from typing import Any

from tests.e2e.conftest import METRICS_BUDGET, Stack, wait_until


def _first_value(stack: Stack, expr: str) -> float | None:
    result = stack.prom_query(expr)
    return float(result[0]["value"][1]) if result else None


def test_native_targets_are_up(stack: Stack) -> None:
    for job in ("app-metrics", "rabbitmq"):

        def _up(job: str = job) -> bool:
            return (
                _first_value(
                    stack,
                    f'up{{job="{job}",compose_project="{stack.project}"}}',
                )
                == 1.0
            )

        wait_until(_up, timeout=METRICS_BUDGET, desc=f"up==1 for {job}")


def test_app_counter_grows(stack: Stack) -> None:
    expr = (
        f'app_events_total{{job="app-metrics",'
        f'compose_project="{stack.project}"}}'
    )
    first = wait_until(
        lambda: _first_value(stack, expr),
        timeout=METRICS_BUDGET,
        desc="first counter sample",
    )
    wait_until(
        lambda: (v := _first_value(stack, expr)) is not None and v > first,
        timeout=70,  # one more 30s scrape plus slack
        desc="counter increased between scrapes",
    )


def test_postgres_exporter_authenticated(stack: Stack) -> None:
    # pg_up == 1 requires a successful connection and authentication.
    # Provenance enrichment (phase 2) attaches compose_project, so the
    # assertion is scoped to this run.
    wait_until(
        lambda: (
            (
                r := stack.prom_query(
                    f'pg_up{{compose_project="{stack.project}"}}'
                )
            )
            and float(r[0]["value"][1]) == 1.0
        ),
        timeout=METRICS_BUDGET,
        desc="pg_up == 1",
    )


def test_self_metrics_via_contract(stack: Stack) -> None:
    # Dogfooding: alloy/prometheus/loki carry the full mandatory
    # metrics.* label set and are scraped by Alloy itself.
    for family, job in (
        ("alloy_build_info", "alloy"),
        ("prometheus_build_info", "prometheus"),
        ("loki_build_info", "loki"),
    ):

        def _present(
            family: str = family, job: str = job
        ) -> list[dict[str, Any]]:
            return stack.prom_query(
                f'{family}{{job="{job}",compose_project="{stack.project}"}}'
            )

        wait_until(_present, timeout=METRICS_BUDGET, desc=f"{family} present")


def test_provenance_labels_on_native_series(stack: Stack) -> None:
    series = wait_until(
        lambda: stack.prom_query(
            f'up{{job="app-metrics",compose_project="{stack.project}"}}'
        ),
        timeout=METRICS_BUDGET,
        desc="app-metrics series",
    )
    labels = series[0]["metric"]
    assert labels["environment"] == "e2e"
    assert labels["team"] == "apps"
    assert labels["collector"] == "alloy"
    assert "app-metrics" in labels["container"]
    assert labels["host"]


def test_fast_profile_target_is_routed_to_fast_pair(stack: Stack) -> None:
    # Manifest 8.2 routing: rabbitmq declares fast-v1, so its target must
    # carry the raw profile label through the shared relabel and land in
    # the fast filter -- and ONLY there. The normal filter's "(normal-v1)?"
    # regex accepts the empty value, so a profile label lost en route
    # would silently reroute the target to the default pair; asserting
    # membership on both filters makes that failure mode visible.
    profile_label = (
        "__meta_docker_container_label_ru_3ops_discovery_metrics_profile"
    )
    name_label = "__meta_docker_container_name"
    rabbitmq = "/" + stack.compose_container("rabbitmq")

    def _shared_sees_profile() -> bool:
        return any(
            t.get(name_label) == rabbitmq and t.get(profile_label) == "fast-v1"
            for t in stack.relabel_target_labels("discovery.relabel.metrics")
        )

    wait_until(
        _shared_sees_profile,
        timeout=METRICS_BUDGET,
        desc="profile label on the shared metrics relabel output",
    )
    fast = stack.relabel_target_labels("discovery.relabel.metrics_fast_v1")
    normal = stack.relabel_target_labels("discovery.relabel.metrics_normal_v1")
    assert any(t.get(name_label) == rabbitmq for t in fast)
    assert not any(t.get(name_label) == rabbitmq for t in normal)


def test_badsecret_target_is_dropped(stack: Stack) -> None:
    # The path-traversal secret-id ("bad/../id") must fail the manifest
    # section 9 keep-rule in 030, so the database relabel keeps ONLY the
    # valid postgres target -- exactly one, not two. Asserting on the
    # relabel output size (not a series label the db pipeline never
    # emits) makes the drop genuinely observable.
    # Positive control first: the valid pipeline is alive, so a size of
    # one is evidence of the drop, not of a broken database domain.
    wait_until(
        lambda: _first_value(stack, "pg_up") == 1.0,
        timeout=METRICS_BUDGET,
        desc="valid postgres pipeline alive",
    )
    # Two valid postgres targets survive (postgres-orders and the
    # basic-v1 postgres-audit); the badsecret target must not make it
    # three.
    kept = stack.relabel_project_targets("discovery.relabel.database_postgres")
    assert kept == 2, (
        f"expected only the two valid postgres targets after the "
        f"secret-id drop, got {kept} (path-traversal id not dropped?)"
    )
