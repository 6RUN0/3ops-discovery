"""
Section 15 usage examples are valid compose input, not just prose.

The examples are the only "how to use the contract" material in the
manifest, and they are copy-pasted verbatim by adopters -- so a broken
one is a broken contract. Compose rejects an unknown top-level key
outright, which is exactly how the anchors example shipped for a while
(`ru.3ops.discovery-common:` instead of `x-3ops-discovery-common:`).

The rule runs in both directions and the two halves contradict each
other, which is why the gate pins both: a top-level key MUST be a known
compose key or carry the `x-` extension prefix, while a key inside a
`labels:` mapping MUST stay reverse-DNS -- compose silently drops an
`x-`-prefixed label key, so the contract namespace could not use it.

Pure YAML parsing on purpose: the static suite must run without Docker.
"""

import pytest
import yaml

from tests.static import manifest_doc as md

#: Top-level keys the compose schema accepts; everything else must be an
#: `x-` extension. Deliberately not exhaustive-by-import: compose has no
#: machine-readable schema we can pin without a network fetch.
COMPOSE_TOP_LEVEL = frozenset(
    {
        "services",
        "networks",
        "volumes",
        "configs",
        "secrets",
        "name",
        "include",
        # Obsolete since compose v2 but still accepted with a warning.
        "version",
    }
)

LABEL_PREFIX = "ru.3ops.discovery."


def _bad_top_level_keys(doc: dict[str, object]) -> list[str]:
    """Top-level keys compose would reject (not known, not `x-`)."""
    return [
        key
        for key in doc
        if key not in COMPOSE_TOP_LEVEL and not key.startswith("x-")
    ]


def _label_maps(doc: dict[str, object]) -> list[dict[str, object]]:
    """Every `labels:` mapping in the document (services and top level)."""
    maps: list[dict[str, object]] = []
    top_labels = doc.get("labels")
    if isinstance(top_labels, dict):
        maps.append(top_labels)
    services = doc.get("services")
    if isinstance(services, dict):
        for service in services.values():
            labels = (
                service.get("labels") if isinstance(service, dict) else None
            )
            if isinstance(labels, dict):
                maps.append(labels)
    return maps


def _examples() -> list[dict[str, object]]:
    docs = [yaml.safe_load(block) for block in md.yaml_blocks("15")]
    assert docs, "section 15 has no yaml examples"
    return [doc for doc in docs if isinstance(doc, dict)]


def _compose_examples() -> list[dict[str, object]]:
    """
    Examples that are whole compose files, not label fragments.

    15.2 shows a bare `labels:` mapping meant to be pasted INTO a service,
    so the compose top-level rule does not apply to it. Everything else is
    treated as a compose file: keying off "has services:" instead would let
    a future example opt out of the gate just by omitting that key.
    """
    files = [doc for doc in _examples() if set(doc) != {"labels"}]
    assert files, "section 15 has no whole-compose example"
    return files


def test_compose_examples_use_valid_top_level_keys() -> None:
    for doc in _compose_examples():
        assert _bad_top_level_keys(doc) == [], (
            "compose rejects unknown top-level keys; use an `x-` extension"
        )


def test_example_label_keys_stay_reverse_dns() -> None:
    # The mirror image of the rule above: an `x-` prefixed key inside
    # `labels:` is parsed as an extension and dropped, so the label would
    # never reach the container.
    seen = 0
    for doc in _examples():
        for labels in _label_maps(doc):
            for key in labels:
                assert key.startswith(LABEL_PREFIX), (
                    f"example label {key!r} is outside the contract namespace"
                )
                seen += 1
    assert seen, "no example labels found in section 15"


def test_anchor_merge_keys_are_not_mistaken_for_labels() -> None:
    # `<<: *anchor` must merge into the label map rather than survive as a
    # literal key -- yaml.safe_load resolves it, so a regression that turns
    # the anchor into a plain key would surface as a non-namespaced label
    # in the test above. Pin the merge itself so the intent is explicit.
    anchors = md.yaml_blocks("15")[0]
    assert "<<: *" in anchors, "the anchors example no longer merges"
    services = yaml.safe_load(anchors)["services"]
    for service in services.values():
        assert service["labels"]["ru.3ops.discovery.enabled"] == "true", (
            "merged anchor did not reach the service labels"
        )


@pytest.mark.parametrize(
    ("key", "rejected"),
    [
        ("ru.3ops.discovery-common", True),
        ("x-3ops-discovery-common", False),
        ("services", False),
    ],
)
def test_checker_flags_the_shipped_regression(
    key: str, rejected: bool
) -> None:
    # The exact defect this gate exists for: reproduced as a unit so the
    # checker itself cannot rot into a no-op.
    assert bool(_bad_top_level_keys({key: {}})) is rejected
