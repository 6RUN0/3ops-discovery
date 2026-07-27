"""Manifest 8.3/10.3 vs 040/050."""

import re

from tests.static import alloy_config as ac
from tests.static import asymmetries
from tests.static import manifest_doc as md


def test_allowlist_is_subset_of_manifest() -> None:
    assert ac.log_profile_allowlist() <= md.log_profiles()


def test_asymmetry_table_is_exact() -> None:
    unimplemented = md.log_profiles() - ac.log_profile_allowlist()
    assert unimplemented == set(asymmetries.LOG_PROFILES_UNIMPLEMENTED)


def test_mixed_stages_are_exclusive_and_named() -> None:
    text = ac.sources()["050_log-profiles.alloy"]
    # Every dispatcher stage carries pipeline_name, so per-stage Loki
    # process metrics stay distinguishable in diagnostics.
    assert text.count("stage.match {") == text.count("pipeline_name")
    # The two mixed-v1 stages must be mutually exclusive: a JSON line
    # with logfmt-looking text inside a value (`{"msg":"raised level=
    # high"}`) would otherwise run both parsers, and logfmt would
    # overwrite the JSON-extracted values in structured metadata.
    selectors = re.findall(r"selector\s*=\s*`([^`]*)`", text)
    mixed = [s for s in selectors if 'log_profile="mixed-v1"' in s]
    assert len(mixed) == 2
    logfmt = next(s for s in mixed if "level|msg|status" in s)
    assert r'!~ "^\\s*\\{"' in logfmt, (
        "mixed-v1 logfmt selector must exclude JSON-shaped lines"
    )
    # And the manifest has to say so. It used to describe the profile
    # with "may", listing two heuristics that overlap, so a second
    # implementer could satisfy 10.3.6 with a pipeline whose output
    # depends on stage order.
    assert "исключающие" in md.section("10.3.6"), (
        "10.3.6 does not state that the mixed-v1 branches are exclusive"
    )


def test_source_consumes_relabeled_targets() -> None:
    # Manifest 10.3.1: logs.enabled=false containers are excluded BEFORE
    # the source. Wiring raw discovery targets into loki.source.docker
    # would tail every opt-out container and ship its lines with an
    # empty label set (the tailer applies the drop rule per line, and a
    # fired drop clears ALL labels), which Loki rejects per-stream.
    assert ac.logs_source_targets() == "discovery.relabel.docker_logs.output"


def test_dispatcher_covers_allowlist_except_raw_passthrough() -> None:
    # raw-v1 is a pass-through by design; mixed-v1 maps to one or MORE
    # stages, so sets (not counts) are compared.
    expected = ac.log_profile_allowlist() - {"raw-v1"}
    assert ac.dispatcher_profiles() == expected


def test_fail_closed_rule_names_the_logs_exception() -> None:
    # The reference is right and the text was wrong: 8.4 said a profile
    # outside the allowlist drops the target "as in every other domain",
    # while 10.3.4 requires that logs never be lost and fall back to
    # raw-v1. Letting the more specific rule win rescued the meaning,
    # but a normative document must not need rescuing. Both places that state
    # the fail-closed rule now have to name the exception.
    for number in ("8.4", "11"):
        body = md.section(number)
        assert "fail-closed" in body, f"section {number} lost the rule"
        assert "10.3.4" in body, (
            f"section {number} states fail-closed without the logs "
            f"exception of 10.3.4"
        )
