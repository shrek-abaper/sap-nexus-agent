"""Tests for governed context data structures (GovernedContext contract).

Design Doc: docs/superpowers/specs/2026-08-03-governed-context-registry-snapshot-design.md
section 3 (核心数据结构).
"""

from __future__ import annotations

import pytest

from sap_nexus_agent.governed_context import (
    PLACEHOLDER_PRINCIPAL,
    GovernedContext,
    PlannerFailure,
    SnapshotDriftError,
    SnapshotLease,
    TrustedPrincipal,
    VisibleCapabilitySet,
    load_principal_from_env,
)
from sap_nexus_agent.planner.capability_card import CapabilityCard, Governance
from sap_nexus_agent.semantic_planning.contracts import (
    RegistrySnapshot,
    SemanticSourceDocuments,
    SnapshotSource,
)


def _fake_snapshot(snapshot_id: str = "sha256:abc123") -> RegistrySnapshot:
    return RegistrySnapshot(
        snapshot_version=1,
        canonicalization_version=1,
        snapshot_id=snapshot_id,
        sources=(
            SnapshotSource(
                path="registry/capabilities.yaml",
                document_version=1,
                digest="sha256:x",
            ),
        ),
    )


def _fake_sources() -> SemanticSourceDocuments:
    return SemanticSourceDocuments(
        capabilities={"capabilities": []},
        executor_bindings={"bindings": []},
        fact_types={"factTypes": []},
        relations={"relations": []},
    )


def _fake_card(capability_id: str = "MM.Inventory.GetAvailability") -> CapabilityCard:
    return CapabilityCard(
        capability_id=capability_id,
        name="Test",
        governance=Governance(
            side_effect="none",
            requires_approval=False,
            data_classification="internal",
        ),
    )


# ---- TrustedPrincipal + PLACEHOLDER ----


def test_placeholder_principal_fields():
    assert PLACEHOLDER_PRINCIPAL.principal_id == "local-user-0001"
    assert PLACEHOLDER_PRINCIPAL.role == "operator"
    assert PLACEHOLDER_PRINCIPAL.data_scope == {"tenantId": "default"}


def test_trusted_principal_is_frozen():
    with pytest.raises(Exception):
        PLACEHOLDER_PRINCIPAL.principal_id = "mutated"  # type: ignore[misc]


# ---- load_principal_from_env ----


def test_load_principal_from_env_defaults_to_placeholder(monkeypatch):
    monkeypatch.delenv("SAP_NEXUS_PRINCIPAL", raising=False)
    principal = load_principal_from_env()
    assert principal == PLACEHOLDER_PRINCIPAL


def test_load_principal_from_env_parses_valid_json(monkeypatch):
    monkeypatch.setenv(
        "SAP_NEXUS_PRINCIPAL",
        '{"principalId":"user-42","role":"admin","dataScope":{"tenantId":"t1"}}',
    )
    principal = load_principal_from_env()
    assert principal.principal_id == "user-42"
    assert principal.role == "admin"
    assert principal.data_scope == {"tenantId": "t1"}


def test_load_principal_from_env_falls_back_on_malformed_json(monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_PRINCIPAL", "{not json")
    principal = load_principal_from_env()
    assert principal == PLACEHOLDER_PRINCIPAL


# ---- GovernedContext ----


def test_governed_context_construction():
    principal = TrustedPrincipal("user-1", "operator", {"tenantId": "t1"})
    ctx = GovernedContext(
        principal=principal,
        scopes=("tenantId:t1",),
        snapshot_id="sha256:abc",
        registry_version=1,
    )
    assert ctx.snapshot_id == "sha256:abc"
    assert ctx.registry_version == 1
    assert ctx.principal.principal_id == "user-1"


def test_governed_context_is_frozen():
    ctx = GovernedContext(
        principal=PLACEHOLDER_PRINCIPAL,
        scopes=(),
        snapshot_id="sha256:x",
        registry_version=1,
    )
    with pytest.raises(Exception):
        ctx.snapshot_id = "mutated"  # type: ignore[misc]


# ---- SnapshotLease ----


def test_snapshot_lease_holds_snapshot_and_sources():
    snapshot = _fake_snapshot()
    sources = _fake_sources()
    lease = SnapshotLease(snapshot=snapshot, sources=sources)
    assert lease.snapshot_id == snapshot.snapshot_id


def test_snapshot_lease_assert_same_passes_when_ids_match():
    snapshot = _fake_snapshot("sha256:match")
    lease = SnapshotLease(snapshot=snapshot, sources=_fake_sources())
    lease.assert_same("sha256:match", stage="planner")  # no exception


def test_snapshot_lease_assert_same_raises_on_drift():
    snapshot = _fake_snapshot("sha256:expected")
    lease = SnapshotLease(snapshot=snapshot, sources=_fake_sources())
    with pytest.raises(SnapshotDriftError) as exc_info:
        lease.assert_same("sha256:different", stage="planner")
    assert "sha256:expected" in str(exc_info.value)
    assert "sha256:different" in str(exc_info.value)


# ---- VisibleCapabilitySet ----


def test_visible_capability_set_construction():
    cards = (_fake_card(),)
    visible = VisibleCapabilitySet(
        cards=cards,
        snapshot_id="sha256:abc",
        principal_id="user-1",
    )
    assert len(visible.cards) == 1
    assert visible.snapshot_id == "sha256:abc"
    assert visible.principal_id == "user-1"


# ---- PlannerFailure ----


def test_planner_failure_construction_with_audit_evidence():
    failure = PlannerFailure(
        error_type="SNAPSHOT_DRIFT",
        message="snapshot drifted at planner stage",
        snapshot_id="sha256:expected",
        audit_evidence={
            "expected_snapshot_id": "sha256:expected",
            "actual_snapshot_id": "sha256:actual",
            "principal_id": "user-1",
            "source_paths": [],
            "stage": "planner",
        },
    )
    assert failure.error_type == "SNAPSHOT_DRIFT"
    assert failure.audit_evidence["expected_snapshot_id"] == "sha256:expected"


def test_planner_failure_error_type_enum_values():
    for error_type in (
        "SNAPSHOT_MISSING",
        "SNAPSHOT_DRIFT",
        "PRINCIPAL_MISMATCH",
        "SOURCE_LOAD_ERROR",
        "VISIBILITY_DENIED",
    ):
        failure = PlannerFailure(
            error_type=error_type,  # type: ignore[arg-type]
            message="test",
            snapshot_id=None,
            audit_evidence={},
        )
        assert failure.error_type == error_type


def test_planner_failure_is_frozen():
    failure = PlannerFailure(
        error_type="SOURCE_LOAD_ERROR",
        message="test",
        snapshot_id=None,
        audit_evidence={},
    )
    with pytest.raises(Exception):
        failure.error_type = "SNAPSHOT_DRIFT"  # type: ignore[misc]
