"""Cadvisor per-container delivery (manifest 14.5, overlay 075)."""

from tests.e2e.conftest import METRICS_BUDGET, Stack, wait_until


def test_sibling_container_metrics_with_full_provenance(
    stack: Stack,
) -> None:
    # Sibling visibility is THE risk of the overlay: with a private
    # cgroup namespace cadvisor would see only the alloy container
    # itself, so asserting on the prometheus service of this project
    # proves the host cgroup namespace works end to end. Scoped by
    # compose_project because a shared daemon exposes foreign
    # containers too.
    series = wait_until(
        lambda: stack.prom_query(
            f"container_cpu_usage_seconds_total{{"
            f'compose_project="{stack.project}",'
            f'compose_service="prometheus"}}'
        ),
        timeout=METRICS_BUDGET,
        desc="cadvisor series for a sibling container",
    )
    labels = series[0]["metric"]
    assert labels["environment"] == "e2e"
    assert labels["team"] == "platform"
    # Exact equality, not substring: container exists to correlate with
    # the container label 020 attaches, and Stack.compose_container()
    # returns the same {project}-{service}-1 name.
    assert labels["container"] == stack.compose_container("prometheus")
    assert labels["collector"] == "alloy"
    assert labels["host"]
    # Pins the manifest 14.5 literal: exporters set job=integrations/<x>.
    assert labels["job"] == "integrations/cadvisor"
    # The mandatory labeldrop: no raw cadvisor label may survive. This
    # also pins the label sanitization of the vendored cadvisor fork
    # (dots/dashes -> underscores, container_label_ prefix): had it
    # differed, environment/team above would simply be absent.
    assert not any(key.startswith("container_label_") for key in labels)
    assert "id" not in labels
    assert "name" not in labels
