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


def test_json_profile_reads_only_objects() -> None:
    # A JSON array or scalar parses but has no keys; set() of a list would
    # report its items as field names.
    for line in ("[1, 2]", '"text"', "7", "null", "{broken"):
        assert keys("generic-json-v1", line) == set(), line
        assert keys("mixed-v1", line) == set(), line


def test_mixed_profile_treats_an_indented_object_as_json() -> None:
    # The dispatcher selector allows leading whitespace before `{`; a
    # trailing-space check would send this line to the logfmt parser.
    assert keys("mixed-v1", '  {"event":"tick"}') == {"event"}
    assert keys("mixed-v1", '{"a": 1}  ') == {"a"}


def test_mixed_profile_parses_logfmt_only_after_a_known_anchor() -> None:
    # The dispatcher sends a line to the logfmt parser only when it carries
    # level=, msg= or status= at the start or after a space.
    assert keys("mixed-v1", "request_id=1 trace_id=2") == set()
    assert keys("mixed-v1", "xlevel=info seq=1") == set()
    assert keys("mixed-v1", "seq=1 level=info") == {"seq", "level"}
