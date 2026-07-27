"""
Manifest 10.1.1 metrics labels vs the values 020 actually accepts.

Every other domain already binds its type allowlist to the manifest --
database.type, the blackbox modules, the snmp modules. The metrics
domain had `regex = "prometheus"` sitting in the config with nothing on
the other end of it, so a second accepted type could be added to either
side alone and both would still look right on their own.
"""

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md

_TYPE = "ru.3ops.discovery.metrics.type"


def test_metrics_type_allowlist_matches_the_manifest() -> None:
    documented = md.domain_label_values("10.1.1", _TYPE)
    assert documented, f"{_TYPE} documents no literal value in 10.1.1"
    assert ac.metrics_type_allowlist() == documented


def test_metrics_type_is_fail_closed() -> None:
    # No empty alternative, unlike database.profile: the label is
    # mandatory (10.1.1), so an unset value must drop the target rather
    # than fall through to a default.
    assert "" not in ac.metrics_type_allowlist()
