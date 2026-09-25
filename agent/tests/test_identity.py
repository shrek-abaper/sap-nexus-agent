"""Tests for Identity Foundation."""

from __future__ import annotations

import pytest

from sap_nexus_agent.identity import (
    IdentityConflict,
    IdentityError,
    IdentityRegistry,
    canonical_identity,
)

IDENTIFIERS = {"material": "P0226750AD", "plant": "5260"}


def test_canonical_identity_is_stable():
    first = canonical_identity("MaterialInfo", IDENTIFIERS)
    second = canonical_identity(
        "MaterialInfo", {"plant": "5260", "material": "P0226750AD"}
    )  # reordered

    assert first == second
    assert first.startswith("id:")


def test_different_values_differ():
    a = canonical_identity("MaterialInfo", IDENTIFIERS)
    b = canonical_identity(
        "MaterialInfo", {"material": "P0226750AD", "plant": "5200"}
    )

    assert a != b


def test_different_object_types_differ():
    assert (
        canonical_identity("InventoryStock", IDENTIFIERS)
        != canonical_identity("MaterialInfo", IDENTIFIERS)
    )


def test_empty_or_missing_inputs_rejected():
    with pytest.raises(IdentityError):
        canonical_identity("MaterialInfo", {})
    with pytest.raises(IdentityError):
        canonical_identity("", IDENTIFIERS)


def test_resolve_new_then_direct():
    reg = IdentityRegistry()
    first = reg.resolve("MaterialInfo", IDENTIFIERS)
    second = reg.resolve("MaterialInfo", IDENTIFIERS)

    assert first.kind == "new"
    assert second.kind == "direct"
    assert first.identity == second.identity


def test_alias_resolves_to_same_identity():
    reg = IdentityRegistry()
    primary = reg.resolve("MaterialInfo", IDENTIFIERS)
    # Alias uses a unique token (EXT-1); only the distinctive key needs binding.
    reg.register_alias(
        primary.identity, "MaterialInfo", {"material": "EXT-1"}
    )
    via_alias = reg.resolve(
        "MaterialInfo", {"material": "EXT-1", "plant": "5260"}
    )

    assert via_alias.kind == "alias"
    assert via_alias.identity == primary.identity


def test_alias_conflict_raises():
    reg = IdentityRegistry()
    identity_a = canonical_identity(
        "MaterialInfo", {"material": "A", "plant": "5260"}
    )
    identity_b = canonical_identity(
        "MaterialInfo", {"material": "B", "plant": "5260"}
    )
    reg.register_alias(
        identity_a, "MaterialInfo", {"material": "EXT-9", "plant": "5260"}
    )

    with pytest.raises(IdentityConflict):
        reg.register_alias(
            identity_b, "MaterialInfo", {"material": "EXT-9", "plant": "5260"}
        )


def test_conflicting_alias_rebind_rejected_at_registration():
    reg = IdentityRegistry()
    identity_a = canonical_identity(
        "MaterialInfo", {"material": "A", "plant": "5260"}
    )
    identity_b = canonical_identity(
        "MaterialInfo", {"material": "B", "plant": "5260"}
    )
    # Binding the same alias token to a different identity must fail when the
    # second alias is registered, before any resolve.
    reg.register_alias(identity_a, "MaterialInfo", {"material": "EXT-X"})
    with pytest.raises(IdentityConflict):
        reg.register_alias(
            identity_b, "MaterialInfo", {"material": "EXT-X"}
        )
