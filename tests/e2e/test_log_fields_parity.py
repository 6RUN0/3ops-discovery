"""Non-indexed log fields per profile equal the manifest 8.3 table."""

import pytest

from tests.e2e.conftest import LOGS_BUDGET, Stack, wait_until
from tests.static import asymmetries
from tests.static import manifest_doc as md
from tools.backends import LogQuery, LogRecord
from tools.log_profiles import LOG_PROFILE_CONTAINERS, keys


@pytest.mark.parametrize("profile", sorted(LOG_PROFILE_CONTAINERS))
def test_non_indexed_fields_are_exactly_the_profile_table(
    profile: str, stack: Stack
) -> None:
    """Pins: Alloy delivers the 8.3 fields the line has, and no others."""
    query = LogQuery(
        stream={
            "compose_project": stack.project,
            "compose_service": LOG_PROFILE_CONTAINERS[profile],
        }
    )

    def _records() -> list[LogRecord] | None:
        return stack.log_records(query) or None

    records = wait_until(
        _records, timeout=LOGS_BUDGET, desc=f"{profile} records"
    )
    table = md.log_profile_fields()[profile]
    derived = set(asymmetries.STORE_DERIVED_LOG_FIELDS.get(stack.backend, {}))
    for record in records:
        assert set(record.fields) - derived == table & keys(
            profile, record.line
        ), record
