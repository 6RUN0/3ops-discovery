"""Manifest 9 vs the secret-id keep-rules in 030."""

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md


def test_every_pipeline_uses_the_manifest_regex() -> None:
    pattern = md.secret_id_pattern()
    regexes = ac.secret_id_regexes()
    assert regexes, "no secret-id keep-rules found"
    assert all(regex == pattern for regex in regexes), (
        f"config regexes {regexes} != manifest {pattern!r}"
    )
