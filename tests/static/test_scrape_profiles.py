"""Manifest 8.2 vs 020_metrics.alloy."""

from tests.static import alloy_config as ac
from tests.static import asymmetries
from tests.static import manifest_doc as md


def test_implemented_pairs_match_manifest_parameters() -> None:
    manifest = md.scrape_profiles()
    for name, params in ac.scrape_pairs().items():
        assert name in manifest, f"{name} is not a manifest 8.2 profile"
        assert params == manifest[name], (
            f"{name}: config {params} != manifest {manifest[name]}"
        )


def test_asymmetry_table_is_exact() -> None:
    manifest = set(md.scrape_profiles())
    implemented = set(ac.scrape_pairs())
    allowed = set(asymmetries.SCRAPE_PROFILES_UNIMPLEMENTED)
    assert implemented | allowed == manifest
    assert implemented & allowed == set()


def test_job_keep_is_fail_closed() -> None:
    # metrics.job is mandatory (manifest 10.1.1) and used to fail open:
    # relabel copied the empty value, the empty label was dropped and
    # prometheus.scrape substituted its own component name as job.
    assert ac.job_presence_keep_regex() == "(.+)"


def test_manifest_states_that_an_empty_mandatory_label_drops() -> None:
    # The two keeps below are the implementation of a rule that lived
    # only in their comments. Section 11 said "an empty value equals an
    # absent label, the domain default applies" -- vacuous for mandatory
    # labels, which have no default. A second implementer reading only
    # the manifest would have let the target through.
    body = md.section("11")
    assert "fail-closed" in body
    for label in ("metrics.port", "metrics.job", "blackbox.port"):
        assert f"`{label}`" in body, (
            f"section 11 does not name {label} among the presence checks"
        )


def test_port_keep_is_fail_closed() -> None:
    # Without a presence keep, a container that declares metrics.enabled
    # but no TCP ports rides the discovery.docker fallback target (no
    # __meta_docker_port_private) straight through keepequal ("" == "")
    # and gets scraped on port 80 (manifest 10.1.1 makes the label
    # mandatory, 11 makes its validation fail-closed).
    assert ac.port_presence_keep_regexes()["metrics"] == "(.+)"


def test_exactly_the_documented_profile_serves_unmarked_targets() -> None:
    # The keep-regex of the default filter carries a trailing "?" so it
    # also matches an unset label. Nothing used to read that marker: the
    # scanner stripped it along with the parentheses, making (fast-v1)
    # and (fast-v1)? indistinguishable. A profile pair copied with the
    # marker left on would scrape every default target twice -- once on
    # its own cadence, once on the copy's -- and pass every gate.
    documented = md.default_profile(
        "10.1.1", "ru.3ops.discovery.metrics.profile"
    )
    assert ac.default_scrape_profiles() == {documented}
    blackbox = md.default_profile(
        "10.4.1", "ru.3ops.discovery.blackbox.profile"
    )
    assert ac.default_blackbox_scrape_profiles() == {blackbox}
