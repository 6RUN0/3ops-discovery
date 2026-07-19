"""Loki delivery assertions: profiles, structured metadata, allowlist."""

import subprocess

from tests.e2e.conftest import LOGS_BUDGET, Stack, wait_until
from tests.static import manifest_doc as md


def test_json_profile_parses_into_structured_metadata(
    stack: Stack,
) -> None:
    base = (
        f'{{service_name="app-logs-json",compose_project="{stack.project}"}}'
    )
    wait_until(
        lambda: stack.loki_entries(base),
        timeout=LOGS_BUDGET,
        desc="json stream present",
    )
    parsed = wait_until(
        lambda: stack.loki_entries(base + ' | trace_id=~".+"'),
        timeout=LOGS_BUDGET,
        desc="json structured metadata",
    )
    assert parsed


def test_logfmt_profile_parses_into_structured_metadata(
    stack: Stack,
) -> None:
    base = (
        f'{{service_name="app-logs-logfmt",compose_project="{stack.project}"}}'
    )
    parsed = wait_until(
        lambda: stack.loki_entries(base + ' | status=~".+"'),
        timeout=LOGS_BUDGET,
        desc="logfmt structured metadata",
    )
    assert parsed


def test_mixed_stream_is_complete_and_partially_parsed(
    stack: Stack,
) -> None:
    base = (
        f'{{service_name="app-logs-mixed",compose_project="{stack.project}"}}'
    )
    entries = wait_until(
        lambda: e if len(e := stack.loki_entries(base)) >= 8 else None,
        timeout=LOGS_BUDGET,
        desc="mixed stream flowing",
    )
    lines = [line for _ts, line in entries]
    # Every renderer kind arrived raw-or-parsed; nothing was dropped:
    # the app cycles 4 kinds, so each must appear.
    assert any(line.startswith("{") for line in lines)
    assert any("msg=tick" in line for line in lines)
    assert any("plain tick number" in line for line in lines)
    assert any("operator note" in line for line in lines)
    parsed = stack.loki_entries(base + ' | trace_id=~".+"')
    assert parsed, "no mixed line gained structured metadata"


def test_unlabeled_container_collected_as_raw(stack: Stack) -> None:
    series = wait_until(
        lambda: stack.loki_series(
            f'{{compose_service="app-logs-raw",'
            f'compose_project="{stack.project}"}}'
        ),
        timeout=LOGS_BUDGET,
        desc="raw default stream",
    )
    assert all(s["log_profile"] == "raw-v1" for s in series)


def test_unknown_profile_degrades_to_raw(stack: Stack) -> None:
    series = wait_until(
        lambda: stack.loki_series(
            f'{{compose_service="app-logs-unknown",'
            f'compose_project="{stack.project}"}}'
        ),
        timeout=LOGS_BUDGET,
        desc="unknown-profile stream",
    )
    assert all(s["log_profile"] == "raw-v1" for s in series)
    assert stack.loki_entries(
        f'{{compose_service="app-logs-unknown",'
        f'compose_project="{stack.project}"}}',
    ), "logs were lost instead of degrading to raw-v1"


def test_silent_optout_with_positive_control(stack: Stack) -> None:
    # Positive control FIRST: prove the container wrote to stdout in the
    # test window, otherwise "no data" would prove a crash, not the
    # opt-out.
    host_logs = subprocess.run(
        [
            "docker",
            "logs",
            "--tail",
            "5",
            stack.compose_container("app-silent"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert host_logs.stdout.strip(), "app-silent produced no stdout"
    assert not stack.loki_series(
        f'{{compose_service="app-silent",compose_project="{stack.project}"}}'
    ), "opt-out container has a Loki stream"


def test_all_stream_labels_within_manifest_allowlist(
    stack: Stack,
) -> None:
    allowlist = md.loki_label_allowlist()
    series = wait_until(
        lambda: stack.loki_series(f'{{compose_project="{stack.project}"}}'),
        timeout=LOGS_BUDGET,
        desc="any stream for this project",
    )
    for labels in series:
        # Loki injects internal book-keeping labels (e.g. __stream_shard__
        # under stream auto-sharding); manifest 6.2 governs contract stream
        # labels only, so ignore the __* ones (as promoted_stream_labels does).
        contract_labels = {n for n in labels if not n.startswith("__")}
        extra = contract_labels - allowlist
        assert not extra, (
            f"stream {labels} carries labels outside manifest 6.2: {extra}"
        )
