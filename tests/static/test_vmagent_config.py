"""
vmagent implementation (implementations/vmagent/) vs the manifest.

The vmagent config is a second implementation of the metrics domain, so
it answers to the same tables as the reference: scrape profiles (8.2),
fail-closed mandatory labels (10.1.1, 11), provenance that a container
label cannot override (6.1, 13.5), no redirects (13.5), the 14.1
defaults and the section 14 registry row with its pinned image tag.
"""

import copy
import re
from pathlib import Path
from typing import Any

import noxfile as nx
import pytest

from tests.static import manifest_doc as md
from tests.static import vmagent_config as vc

#: Section 14.1 parameters that belong to the metrics domain and its output.
METRICS_ENV = {
    "RU_3OPS_DISCOVERY_DOCKER_HOST",
    "RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL",
    "RU_3OPS_DISCOVERY_REMOTE_WRITE_URL",
    "RU_3OPS_DISCOVERY_HOSTNAME",
}


def test_profiles_match_manifest() -> None:
    assert vc.profile_timings() == {
        name: (row["interval"], row["timeout"])
        for name, row in md.scrape_profiles().items()
    }


def test_unknown_profile_is_dropped() -> None:
    assert vc.profile_keep_regex() == (
        "(" + "|".join(sorted(md.scrape_profiles())) + ")?"
    )


def test_redirects_are_not_followed() -> None:
    assert all(
        c.get("follow_redirects") is False for c in vc.load()["scrape_configs"]
    )


def test_mandatory_labels_fail_closed() -> None:
    for label in ("metrics_port", "metrics_job"):
        assert vc.has_presence_keep(
            f"__meta_docker_container_label_ru_3ops_discovery_{label}"
        )
    assert vc.has_keep_if_equal("__meta_docker_port_private")


def test_provenance_is_set_after_user_labels() -> None:
    order = vc.target_label_order()
    for label in ("container", "collector", "host"):
        assert order.index(label) > max(
            order.index(u) for u in ("job", "instance", "environment", "team")
        )
    assert vc.static_value("collector") == "vmagent"


def test_entrypoint_defaults_match_manifest() -> None:
    table = md.env_defaults()
    defaults = vc.entrypoint_defaults()
    assert set(defaults) == METRICS_ENV
    for name, default in defaults.items():
        if name != "RU_3OPS_DISCOVERY_HOSTNAME":
            assert default == table[name]
    # The 14.1 cell is prose ("the collector's hostname"), not a value.
    assert defaults["RU_3OPS_DISCOVERY_HOSTNAME"] == "$(hostname)"


def test_every_placeholder_has_an_entrypoint_default() -> None:
    # vmagent keeps an unset %{NAME} as literal text and passes -dryRun, so
    # a variable the entrypoint does not default breaks discovery at
    # runtime unseen.
    assert vc.placeholders()
    assert vc.placeholders() <= set(vc.entrypoint_defaults())


def test_vmagent_pin_matches_registry() -> None:
    assert md.implementation_agent("vmagent").endswith(
        nx.VMAGENT_IMAGE.split(":")[1]
    )


def test_e2e_overlay_vmagent_image_matches_pin() -> None:
    # vmagent_check and the e2e overlay must run the same pinned tag.
    overlay = nx.REPO / "tests/e2e/stack/docker-compose.vmagent.yml"
    images = set(
        re.findall(
            r"victoriametrics/vmagent:[\w.]+", overlay.read_text("utf-8")
        )
    )
    assert images == {nx.VMAGENT_IMAGE}


def test_registry_lists_vmagent_for_metrics_only() -> None:
    assert md.implementations()["vmagent"] == {"metrics"}


def test_unknown_implementation_agent_is_an_anchor_error() -> None:
    with pytest.raises(md.AnchorError, match="no-such-agent"):
        md.implementation_agent("no-such-agent")


def test_vmagent_check_runs_through_the_entrypoint_both_ways() -> None:
    # One run proves the 14.1 defaults alone yield a loadable config, the
    # other the e2e values, tcp:// docker host and empty hostname included.
    assert nx.VMAGENT_CHECK_ENVS["defaults"] == {}
    assert set(nx.VMAGENT_CHECK_ENVS["e2e"]) == METRICS_ENV
    args = nx.vmagent_check_args({"A": "b"})
    assert args[args.index("-e") + 1] == "A=b"
    mount = args[args.index("-v") + 1]
    assert mount.split(":")[0].startswith("/")
    assert args[-3:] == [
        nx.VMAGENT_IMAGE,
        "/etc/vmagent/entrypoint.sh",
        "-dryRun",
    ]


def _rules() -> list[dict[str, Any]]:
    return copy.deepcopy(vc.relabel_rules())


def _default_profile() -> str:
    return md.default_profile("10.1.1", "ru.3ops.discovery.metrics.profile")


def test_only_the_default_profile_serves_unmarked_targets() -> None:
    assert vc.default_scrape_profiles() == {_default_profile()}


def test_default_profile_gate_catches_a_lost_optional_marker() -> None:
    # Without the "?" an unlabelled target passes the profile keep, gets
    # no interval rule and is scraped at vmagent's global 1m default.
    rules = _rules()
    for rule in rules:
        if rule.get("regex") == f"({_default_profile()})?":
            rule["regex"] = f"({_default_profile()})"
    assert vc.default_scrape_profiles(rules) == set()


def test_default_profile_gate_catches_half_a_default() -> None:
    rules = _rules()
    for rule in rules:
        if (
            rule.get("target_label") == "__scrape_timeout__"
            and rule.get("regex") == f"({_default_profile()})?"
        ):
            rule["regex"] = f"({_default_profile()})"
    with pytest.raises(vc.VmagentConfigError, match="disagree"):
        vc.default_scrape_profiles(rules)


def _keep_if_equal_index(rules: list[dict[str, Any]]) -> int:
    return next(
        i
        for i, rule in enumerate(rules)
        if rule.get("action") == "keep_if_equal"
    )


def test_port_match_gate_catches_a_wrong_comparand() -> None:
    rules = _rules()
    rules[_keep_if_equal_index(rules)]["source_labels"] = [
        "__meta_docker_port_private",
        "__meta_docker_port_public",
    ]
    assert not vc.has_keep_if_equal("__meta_docker_port_private", rules)


def test_port_match_gate_catches_a_missing_or_late_copy() -> None:
    rules = _rules()
    copy_rule = next(
        rule for rule in rules if rule.get("target_label") == vc.PORT_COPY
    )
    rules.remove(copy_rule)
    assert not vc.has_keep_if_equal("__meta_docker_port_private", rules)
    rules.insert(_keep_if_equal_index(rules) + 1, copy_rule)
    assert not vc.has_keep_if_equal("__meta_docker_port_private", rules)


def test_port_match_gate_catches_a_copy_of_another_label() -> None:
    rules = _rules()
    copy_rule = next(
        rule for rule in rules if rule.get("target_label") == vc.PORT_COPY
    )
    copy_rule["source_labels"] = [
        "__meta_docker_container_label_ru_3ops_discovery_metrics_job"
    ]
    assert not vc.has_keep_if_equal("__meta_docker_port_private", rules)


def test_vmagent_check_args_are_the_exact_docker_run_command() -> None:
    """Pins every flag: a changed literal runs a different command."""
    assert nx.vmagent_check_args({"A": "b", "C": ""}) == [
        "docker",
        "run",
        "--rm",
        "-e",
        "A=b",
        "-e",
        "C=",
        "-v",
        f"{nx.VMAGENT_DIR}:/etc/vmagent:ro",
        "--entrypoint",
        "/bin/sh",
        nx.VMAGENT_IMAGE,
        "/etc/vmagent/entrypoint.sh",
        "-dryRun",
    ]


def _with_rules(
    monkeypatch: pytest.MonkeyPatch, rules: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(vc, "relabel_rules", lambda: rules)


def test_presence_keep_needs_action_label_and_regex_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A keep rule with a wrong action, label or regex is no presence keep."""
    label = "L"
    keep = {"action": "keep", "source_labels": [label], "regex": ".+"}
    _with_rules(monkeypatch, [keep])
    assert vc.has_presence_keep(label) is True
    for broken in (
        {**keep, "action": "drop"},
        {**keep, "source_labels": ["other"]},
        {**keep, "regex": "x"},
    ):
        _with_rules(monkeypatch, [broken])
        assert vc.has_presence_keep(label) is False


def test_presence_keep_defaults_the_action_to_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rule without an action is a replace and never a presence keep."""
    _with_rules(monkeypatch, [{"source_labels": ["L"], "regex": "(.+)"}])
    assert vc.has_presence_keep("L") is False


def _port_copy(**extra: Any) -> dict[str, Any]:
    return {
        "source_labels": [vc.PORT_LABEL],
        "target_label": vc.PORT_COPY,
        **extra,
    }


def _port_check() -> dict[str, Any]:
    return {"action": "keep_if_equal", "source_labels": ["P", vc.PORT_COPY]}


def test_port_match_accepts_explicit_default_copy_options() -> None:
    """A copy rule spelling out the default regex and replacement counts."""
    rules = [_port_copy(regex="(.*)", replacement="$1"), _port_check()]
    assert vc.has_keep_if_equal("P", rules) is True


def test_port_match_rejects_a_copy_with_another_regex_or_replacement() -> None:
    """A copy rule that rewrites the port value fails the port match."""
    for extra in ({"regex": "(x)"}, {"replacement": "const"}):
        rules = [_port_copy(**extra), _port_check()]
        assert vc.has_keep_if_equal("P", rules) is False


def test_port_match_without_any_copy_is_a_real_false() -> None:
    """No copy rule must yield False, never a falsy None."""
    assert vc.has_keep_if_equal("P", [_port_check()]) is False
    assert vc.has_keep_if_equal("P", []) is False


def test_static_value_ignores_rules_with_a_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rule driven by a source label is not a constant; skip it."""
    _with_rules(
        monkeypatch,
        [
            {"target_label": "t", "replacement": "const"},
            {"target_label": "t", "replacement": "x", "source_labels": ["s"]},
        ],
    )
    assert vc.static_value("t") == "const"


def test_static_value_error_names_label_and_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error says which label has how many static rules."""
    _with_rules(monkeypatch, [])
    with pytest.raises(vc.VmagentConfigError, match=r"^t: 0 static rules$"):
        vc.static_value("t")


def test_relabel_rules_error_names_the_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error reports how many scrape_configs were found."""
    monkeypatch.setattr(vc, "load", lambda: {"scrape_configs": [{}, {}]})
    with pytest.raises(
        vc.VmagentConfigError,
        match=r"^expected one scrape_config for metrics, got 2$",
    ):
        vc.relabel_rules()


def test_profile_keep_regex_error_names_the_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error reports how many profile keep rules were found."""
    _with_rules(monkeypatch, [])
    with pytest.raises(vc.VmagentConfigError, match=r"^0 profile keep rules$"):
        vc.profile_keep_regex()


def test_timing_rule_errors_name_the_offender() -> None:
    """Timing-rule errors name the target label or the offending regex."""
    undriven = [{"target_label": "__scrape_interval__", "regex": "(a)"}]
    with pytest.raises(
        vc.VmagentConfigError,
        match=r"^__scrape_interval__ not driven by the profile$",
    ):
        vc.profile_timings(undriven)
    odd = [
        {
            "target_label": "__scrape_timeout__",
            "source_labels": [vc.PROFILE_LABEL],
            "regex": "a|b",
        }
    ]
    with pytest.raises(
        vc.VmagentConfigError, match=r"^unexpected regex 'a\|b'$"
    ):
        vc.profile_timings(odd)


def test_profile_timings_reads_the_rules_it_is_given() -> None:
    """Timings come from the rules passed in, not from the real scrape.yml."""
    rules = [
        {
            "target_label": target,
            "source_labels": [vc.PROFILE_LABEL],
            "regex": "(p)",
            "replacement": value,
        }
        for target, value in (
            ("__scrape_interval__", "7s"),
            ("__scrape_timeout__", "3s"),
        )
    ]
    assert vc.profile_timings(rules) == {"p": ("7s", "3s")}


def test_entrypoint_defaults_errors_name_the_problem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Diverging or missing defaults fail with a message naming the cause."""
    script = tmp_path / "entrypoint.sh"
    monkeypatch.setattr(vc, "ENTRYPOINT", script)
    script.write_text(
        "${RU_3OPS_DISCOVERY_X:-a} ${RU_3OPS_DISCOVERY_X:-b}",
        encoding="utf-8",
    )
    with pytest.raises(
        vc.VmagentConfigError,
        match=r"^RU_3OPS_DISCOVERY_X has diverging defaults$",
    ):
        vc.entrypoint_defaults()
    script.write_text("nothing here", encoding="utf-8")
    with pytest.raises(
        vc.VmagentConfigError, match=r"^no \$\{NAME:-default\} in .*entrypoint"
    ):
        vc.entrypoint_defaults()


class _FakeSession:
    """Records what a nox session body would run, without running it."""

    def __init__(self, posargs: list[str] | None = None) -> None:
        self.env: dict[str, str] = {}
        self.posargs = posargs or []
        self.runs: list[tuple[Any, ...]] = []

    def run(self, *args: Any, external: bool = False) -> None:  # noqa: ARG002
        self.runs.append(args)


@pytest.mark.parametrize(
    ("session_name", "backend", "impl", "conformance"),
    [
        ("e2e", "prometheus-loki", "alloy", False),
        ("e2e_victoria", "victoria", "alloy", False),
        ("e2e_vmagent", "prometheus-loki", "vmagent", True),
        ("e2e_vmagent_victoria", "victoria", "vmagent", True),
    ],
)
def test_e2e_sessions_set_both_axes_explicitly(
    session_name: str, backend: str, impl: str, conformance: bool
) -> None:
    """Only vmagent sessions drop Alloy-internals checks; posargs pass."""
    session = _FakeSession(["-k", "x"])
    getattr(nx, session_name)(session)
    assert session.env == {
        "RU_3OPS_DISCOVERY_E2E_BACKEND": backend,
        "RU_3OPS_DISCOVERY_E2E_METRICS_IMPL": impl,
    }
    argv = list(session.runs[0])
    assert argv[:4] == ["uv", "run", "pytest", "tests/e2e"]
    # The per-test budget is tuning; only its presence is the contract.
    assert argv[argv.index("-o") + 1].startswith("timeout=")
    assert argv[-2:] == ["-k", "x"]
    assert ("-m" in argv) is conformance
    if conformance:
        assert argv[argv.index("-m") + 1] == "not alloy_internals"
