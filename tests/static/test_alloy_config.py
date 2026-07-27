"""Unit tests pinning the alloy source scanner to the real config."""

from tests.static import alloy_config as ac


def test_sources_lists_all_base_files() -> None:
    assert len(ac.sources()) == 7
    assert "020_metrics.alloy" in ac.sources()


def test_blackbox_module_allowlist_is_consistent() -> None:
    # The relabel keep-rule and the exporter config must define the same
    # module set: a module the relabel accepts but the exporter cannot probe
    # (or vice versa) is a silent hole.
    assert ac.blackbox_config_modules() == {"http_2xx"}
    assert ac.blackbox_relabel_modules() == {"http_2xx"}


def test_blackbox_scrape_pairs() -> None:
    assert ac.blackbox_scrape_pairs() == {
        "normal-v1": {"interval": "30s", "timeout": "10s"},
    }


def test_env_defaults_extracts_coalesce_literals() -> None:
    env = ac.env_defaults()
    assert env["RU_3OPS_DISCOVERY_DOCKER_REFRESH_INTERVAL"] == {"30s"}
    assert env["RU_3OPS_DISCOVERY_SECRETS_DIR"] == {"/run/alloy-secrets"}


def test_no_env_call_lacks_a_default() -> None:
    assert ac.env_calls_without_default() == set()


def test_scrape_pairs() -> None:
    assert ac.scrape_pairs() == {
        "normal-v1": {"interval": "30s", "timeout": "10s"},
    }


def test_log_profile_allowlist() -> None:
    assert ac.log_profile_allowlist() == {
        "raw-v1",
        "generic-json-v1",
        "generic-logfmt-v1",
        "mixed-v1",
        "python-stacktrace-v1",
        "java-stacktrace-v1",
    }


def test_dispatcher_profiles() -> None:
    assert ac.dispatcher_profiles() == {
        "generic-json-v1",
        "generic-logfmt-v1",
        "mixed-v1",
        "python-stacktrace-v1",
        "java-stacktrace-v1",
    }


def test_promoted_stream_labels() -> None:
    labels = ac.promoted_stream_labels()
    assert {"container", "log_profile", "service_name", "source"} <= labels
    assert not any(name.startswith("__") for name in labels)


def test_db_types_implemented() -> None:
    assert ac.db_types_implemented() == {
        "postgres",
        "mysql",
        "mariadb",
        "redis",
        "mongodb",
    }


def test_secret_id_regexes() -> None:
    # One keep-rule per pipeline: postgres, mysql(+mariadb), redis, mongodb.
    assert (
        ac.secret_id_regexes()
        == [
            "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$",
        ]
        * 4
    )


def test_db_default_ports() -> None:
    # mariadb shares the mysql pipeline, so it has no own component/port.
    assert ac.db_default_ports() == {
        "postgres": "5432",
        "mysql": "3306",
        "redis": "6379",
        "mongodb": "27017",
    }


def test_host_log_stream_labels() -> None:
    assert ac.host_log_stream_labels() == {"host", "collector", "source"}


def test_snmp_scrape_pairs_from_overlay() -> None:
    pairs = ac.snmp_scrape_pairs()
    assert pairs == {"snmp-standard-v1": {"interval": "60s", "timeout": "30s"}}


def test_snmp_relabel_modules_allowlist() -> None:
    assert ac.snmp_relabel_modules() == {"if_mib"}


def test_cadvisor_relabel_target_labels() -> None:
    assert ac.cadvisor_relabel_target_labels() == {
        "collector",
        "host",
        "container",
        "environment",
        "team",
        "compose_project",
        "compose_service",
    }


def test_cadvisor_allowlist_extractor() -> None:
    labels = ac.cadvisor_allowlisted_labels()
    assert "ru.3ops.discovery.environment" in labels
    assert len(labels) == 4
