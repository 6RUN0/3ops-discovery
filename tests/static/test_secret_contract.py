"""Manifest 9 vs the secret-id keep-rules in 030."""

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md


def test_every_pipeline_uses_the_manifest_regex() -> None:
    pattern = md.secret_id_pattern()
    regexes = ac.secret_id_regexes()
    assert regexes, "no secret-id keep-rules found"
    assert all(regex == pattern for regex in regexes), (
        f"config regexes {regexes} != manifest {pattern!r}"
    )


def test_secret_formats_cover_implemented_types() -> None:
    formats = md.secret_formats()
    implemented = ac.db_types_implemented()
    missing = implemented - set(formats)
    assert missing == set(), (
        f"types without a documented .dsn format: {missing}"
    )


def test_secret_format_keys_are_clean_type_names() -> None:
    # Regression: the grouped `mysql`, `mariadb` row in section 9 must
    # yield bare keys, not backtick-laden fragments (split-before-_plain).
    formats = md.secret_formats()
    assert {"mysql", "mariadb"} <= set(formats)
    assert all("`" not in typ and typ == typ.strip() for typ in formats)
