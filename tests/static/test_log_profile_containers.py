"""The e2e log-field parity check covers every shipped log profile."""

from tests.static import asymmetries
from tests.static import manifest_doc as md
from tools.log_profiles import LOG_PROFILE_CONTAINERS, keys


def test_profile_containers_cover_shipped_profiles() -> None:
    shipped = set(md.log_profile_fields()) - set(
        asymmetries.LOG_PROFILES_UNIMPLEMENTED
    )
    assert set(LOG_PROFILE_CONTAINERS) == shipped


def test_keys_follow_the_profile_parser() -> None:
    json_line = '{"event":"tick","level":"info","seq":1}'
    logfmt_line = "level=info msg=tick status=200 seq=1"
    note = "operator note 3: raised level= to high, msg follows"
    assert keys("generic-json-v1", json_line) == {"event", "level", "seq"}
    assert keys("generic-json-v1", logfmt_line) == set()
    assert keys("generic-logfmt-v1", logfmt_line) == {
        "level",
        "msg",
        "status",
        "seq",
    }
    assert keys("mixed-v1", json_line) == {"event", "level", "seq"}
    assert keys("mixed-v1", logfmt_line) >= {"level", "status"}
    assert keys("mixed-v1", note) == set()
    assert keys("raw-v1", json_line) == set()
