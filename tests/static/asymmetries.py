"""
Allowed "manifest is wider than the config" asymmetries.

One explicit data structure instead of exceptions scattered through
check code: every deliberate gap is listed with its reason, so widening
the table is a visible diff-level decision. Entries marked "phase 2"
leave the table when those pipelines land in phase 2.

The subset invariant is a property of the REFERENCE config; user
overlay names (manifest customization section) are legal by pattern
and are not checked by these gates.
"""

SCRAPE_PROFILES_UNIMPLEMENTED: dict[str, str] = {
    "fast-v1": "reference ships only the normal-v1 pair (manifest 14)",
    "slow-v1": "reference ships only the normal-v1 pair (manifest 14)",
}

LOG_PROFILES_UNIMPLEMENTED: dict[str, str] = {
    "app-type-1-v1": "named example of a specialized pipeline, not a "
    "shipped profile (manifest 8.3)",
    "nginx-json-v1": "specialized pipeline example, not shipped "
    "(manifest 8.3)",
}

#: All manifest 10.2 database types are implemented as of phase 2.
DB_TYPES_UNIMPLEMENTED: dict[str, str] = {}

DB_PROFILES_UNHANDLED: dict[str, str] = {
    "basic-v1": "reference ignores database.profile; exporters run "
    "with default collectors",
    "standard-v1": "reference ignores database.profile",
    "extended-v1": "reference ignores database.profile",
}
