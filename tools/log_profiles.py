"""
Log profile helpers shared by the e2e parity check and its static guard.

Pure (no Docker, no fixtures), so a `tests/static` test can import it.
"""

from __future__ import annotations

import json
import re

#: Log profile -> compose service of the e2e stack that logs under it.
LOG_PROFILE_CONTAINERS: dict[str, str] = {
    "raw-v1": "app-logs-raw",
    "generic-json-v1": "app-logs-json",
    "generic-logfmt-v1": "app-logs-logfmt",
    "mixed-v1": "app-logs-mixed",
    "python-stacktrace-v1": "app-logs-pytrace",
    "java-stacktrace-v1": "app-logs-jtrace",
}

#: A logfmt pair with a non-empty bare or quoted value. An empty value
#: (`level= to`) extracts nothing, so it is not a field.
_LOGFMT_PAIR = re.compile(r'(?:^|\s)([^\s="]+)=(?:"[^"]+"|[^\s"=][^\s]*)')


#: The mixed-v1 dispatcher sends a line to the logfmt parser only when one of
#: these keys starts the line or follows a space (050_log-profiles.alloy).
_LOGFMT_ANCHOR = re.compile(r"(?:^|\s)(?:level|msg|status)=")


def _json_keys(line: str) -> set[str]:
    """Top-level keys of a JSON object line; empty for anything else."""
    try:
        parsed = json.loads(line)
    except ValueError:
        return set()
    return set(parsed) if isinstance(parsed, dict) else set()


def _logfmt_keys(line: str) -> set[str]:
    """Keys of the non-empty key=value pairs in a logfmt line."""
    return set(_LOGFMT_PAIR.findall(line))


def keys(profile: str, line: str) -> set[str]:
    """
    Field names the line itself carries, as the profile's parser sees them.

    Profiles without a structural parser, and a line the parser cannot
    read, carry none.
    """
    if profile == "generic-json-v1":
        return _json_keys(line)
    if profile == "generic-logfmt-v1":
        return _logfmt_keys(line)
    if profile == "mixed-v1":
        if line.lstrip().startswith("{"):
            return _json_keys(line)
        if _LOGFMT_ANCHOR.search(line):
            return _logfmt_keys(line)
        return set()
    return set()
