"""Manifest 14 file table vs alloy/ contents; image pin."""

import re
from pathlib import Path

from noxfile import ALLOY_IMAGE

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
