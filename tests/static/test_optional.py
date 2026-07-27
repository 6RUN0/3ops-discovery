"""Customization gates (manifest 14.x)."""

from tests.static import alloy_config as ac
from tests.static import manifest_doc as md


def test_optional_files_do_not_collide_with_each_other() -> None:
    # The base-vs-optional check below unions all overlays first, so a
    # same-named component in two overlays is invisible to it; only the
    # Docker-bound alloy_check (all-snmp combo) would catch it. Fail in
    # the offline gate instead: any combo containing both files breaks.
    seen: dict[str, str] = {}
    for fname, names in sorted(ac.optional_component_names_by_file().items()):
        for name in sorted(names):
            assert name not in seen, (
                f"{name} declared in both {seen[name]} and {fname}"
            )
            seen[name] = fname


def test_optional_names_do_not_collide_with_base() -> None:
    collide = ac.base_component_names() & ac.optional_component_names()
    assert collide == set(), f"optional redeclares base components: {collide}"


def test_optional_files_match_manifest_table() -> None:
    on_disk = set(ac.optional_sources())
    assert on_disk == md.optional_files()


def test_extension_points_exist_in_base() -> None:
    # Every export an optional file references must be a real base
    # component (anti-drift); and every documented extension point (14.4)
    # must exist in base. Documented exports carry a trailing
    # .receiver/.targets/.input; strip it to get the component key that
    # base_component_names() returns.
    referenced = ac.extension_point_targets()
    assert referenced <= ac.base_component_names()
    documented = {export.rsplit(".", 1)[0] for export in md.extension_points()}
    missing = documented - ac.base_component_names()
    assert missing == set(), f"documented extension points absent: {missing}"


def test_overlays_only_use_documented_exports() -> None:
    # Existing in base is a weaker property than being published. 14.4
    # calls itself the public API of the base configuration, stable
    # within a minor version -- so an overlay reaching into an internal
    # stage of a domain pipeline (the output of a shared relabel, say)
    # would be depending on something nobody promised to keep, and the
    # subset-of-base check above would have said nothing.
    undocumented = ac.extension_point_exports() - md.extension_points()
    assert undocumented == set(), (
        f"overlays consume base exports absent from manifest 14.4: "
        f"{sorted(undocumented)}"
    )
