"""Manifest 14 file table vs alloy/ contents; image pin."""

import re
from pathlib import Path

import pytest
from noxfile import (
    ALLOY_IMAGE,
    AlloyFmtError,
    alloy_config_mount,
    alloy_fmt_verdict,
)

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md

_COMPOSE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "e2e"
    / "stack"
    / "docker-compose.yml"
)


def test_file_table_matches_directory_both_ways() -> None:
    assert md.base_files() == set(ac.sources())


def test_alloy_check_image_matches_manifest_pin() -> None:
    assert f"grafana/alloy:{md.alloy_image_tag()}" == ALLOY_IMAGE


def test_e2e_compose_alloy_image_matches_pin() -> None:
    # The manifest pins the Alloy tag; alloy_check and the e2e stack must
    # both run exactly it. This binds the compose image to the same pin
    # so the two never drift silently.
    images = set(
        re.findall(r"grafana/alloy:[\w.]+", _COMPOSE.read_text("utf-8"))
    )
    assert images == {ALLOY_IMAGE}, (
        f"compose alloy image(s) {images} != pinned {ALLOY_IMAGE!r}"
    )


def test_fmt_verdict_separates_a_diff_from_a_docker_failure() -> None:
    # CI once reported every base file as unformatted because the runner
    # could not obtain the image and 125 was read as "needs reformatting".
    # A verdict may only be drawn from the codes the formatter defines.
    assert alloy_fmt_verdict(0, "") is False
    assert alloy_fmt_verdict(1, "is not formatted correctly") is True
    with pytest.raises(AlloyFmtError, match="docker exited 125"):
        alloy_fmt_verdict(125, "Unable to find image locally")


def test_config_mount_source_must_be_absolute() -> None:
    # docker reads a relative -v source as a NAMED VOLUME, not a host
    # directory: `.nox/alloy_check/tmp/base` broke CI with "invalid
    # characters for a local volume name" while a laxer local docker
    # took it. The gate must not depend on which docker runs it.
    assert alloy_config_mount(Path("/tmp/cfg")) == "/tmp/cfg:/etc/alloy:ro"
    with pytest.raises(ValueError, match="must be absolute"):
        alloy_config_mount(Path(".nox/alloy_check/tmp/base"))


def test_fmt_verdict_reports_the_cause_it_was_given() -> None:
    # The stderr was captured and dropped before, which is why the CI log
    # named no cause at all; it must reach the failure message.
    with pytest.raises(AlloyFmtError, match="toomanyrequests"):
        alloy_fmt_verdict(125, "Error response from daemon: toomanyrequests")
    with pytest.raises(AlloyFmtError, match="<no stderr>"):
        alloy_fmt_verdict(126, "   ")
