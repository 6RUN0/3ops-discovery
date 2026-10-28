"""The ci_local session: act arguments for the GitHub workflows."""

import re

import yaml
from noxfile import (
    ACT_RUNNER_IMAGE,
    ACT_SHARED_TMP,
    ACT_WORKFLOWS,
    WORKFLOWS_DIR,
    act_args,
)


def _option(args: list[str], flag: str) -> list[str]:
    return [args[i + 1] for i, arg in enumerate(args) if arg == flag]


def test_runner_image_is_pinned_by_digest() -> None:
    """Pins the version rule: a moving tag would change the runner silently."""
    assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", ACT_RUNNER_IMAGE)


def test_every_workflow_target_exists_with_its_event() -> None:
    """Pins the event per workflow: act runs no job whose `on:` lacks it."""
    for file, event in ACT_WORKFLOWS.values():
        doc = yaml.safe_load((WORKFLOWS_DIR / file).read_text(encoding="utf-8"))
        # PyYAML reads the bare key `on` as the boolean True.
        assert event in doc[True], (file, event)


def test_jobs_run_one_at_a_time_on_the_pinned_runner() -> None:
    """Pins serial jobs: two e2e stacks at once contend for one daemon."""
    args = act_args("ci", [], {})
    assert _option(args, "--concurrent-jobs") == ["1"]
    assert _option(args, "-P") == [f"ubuntu-latest={ACT_RUNNER_IMAGE}"]


def test_pytest_temp_dirs_live_on_a_path_shared_with_the_host() -> None:
    """
    Pins the e2e mount fix: the job container drives the host daemon.

    A pytest temp dir inside the job container does not exist on the
    host, so compose would mount an empty directory as the Alloy config.
    """
    args = act_args("e2e", [], {})
    assert _option(args, "--container-options") == [
        f"-v {ACT_SHARED_TMP}:{ACT_SHARED_TMP}"
    ]
    (addopts,) = _option(args, "--env")
    basetemp = addopts.removeprefix("PYTEST_ADDOPTS=--basetemp=")
    assert basetemp.startswith(f"{ACT_SHARED_TMP}/")


def test_cells_narrow_the_e2e_matrix() -> None:
    args = act_args("e2e", ["e2e_vector", "e2e"], {})
    assert _option(args, "--matrix") == ["session:e2e_vector", "session:e2e"]


def test_github_token_is_forwarded_by_name_only() -> None:
    """Pins the secret rule: the token value never reaches the argv."""
    args = act_args("ci", [], {"GITHUB_TOKEN": "value-that-must-not-leak"})
    assert _option(args, "-s") == ["GITHUB_TOKEN"]
    assert not any("value-that-must-not-leak" in arg for arg in args)
    assert "-s" not in act_args("ci", [], {})
