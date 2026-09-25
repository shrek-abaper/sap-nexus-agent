"""Tests for the WRITE state transition chain."""

from __future__ import annotations

import pytest

from sap_nexus_agent.approval import (
    ApprovalRecord,
    ApprovalState,
    StateTransition,
    approve,
    create_approval_record,
    mark_executed,
    reject,
)


@pytest.fixture()
def record():
    return create_approval_record(
        "MM.PR.CreateDraft",
        {"material": "P0226750AD", "plant": "5260", "quantity": "100"},
        approver="tester",
    )


def test_create_records_initial_pending_transition(record):
    assert record.status == ApprovalState.pending
    assert len(record.transitions) == 1
    first = record.transitions[0]
    assert first.from_state is None
    assert first.to_state == "pending"
    assert first.event == "approval-created"
    assert first.actor == "tester"


def test_approve_appends_transition_with_evidence(record):
    approved = approve(record, evidence_ref="gateway-validate:trace-1")

    assert approved.status == ApprovalState.approved
    assert len(approved.transitions) == 2
    migration = approved.transitions[-1]
    assert migration.from_state == "pending"
    assert migration.to_state == "approved"
    assert migration.event == "approved"
    assert migration.evidence_ref == "gateway-validate:trace-1"


def test_mark_executed_appends_transition(record):
    approved = approve(record)
    executed = mark_executed(approved, evidence_ref="gateway-execute:trace-2")

    assert executed.status == ApprovalState.executed
    assert len(executed.transitions) == 3
    migration = executed.transitions[-1]
    assert migration.from_state == "approved"
    assert migration.to_state == "executed"
    assert migration.evidence_ref == "gateway-execute:trace-2"


def test_reject_appends_transition(record):
    rejected = reject(record, evidence_ref="user-reject")

    assert rejected.status == ApprovalState.rejected
    assert len(rejected.transitions) == 2
    migration = rejected.transitions[-1]
    assert migration.to_state == "rejected"
    assert migration.evidence_ref == "user-reject"


def test_chain_order_matches_history(record):
    executed = mark_executed(approve(record))
    states = [t.to_state for t in executed.transitions]

    assert states == ["pending", "approved", "executed"]


def test_chain_is_immutable_and_append_only(record):
    approved = approve(record)

    # original record unchanged (frozen, append-only).
    assert len(record.transitions) == 1
    with pytest.raises((AttributeError, TypeError)):
        record.transitions[0] = approved.transitions[-1]  # type: ignore[index]


def test_illegal_transition_does_not_append(record):
    # executed is not reachable directly from pending.
    with pytest.raises(Exception):  # noqa: B017, PT011
        mark_executed(record)

    assert len(record.transitions) == 1


def test_round_trip_persists_transitions(record):
    executed = mark_executed(approve(record, "ev-1"), "ev-2")
    payload = executed.to_dict()
    restored = ApprovalRecord.from_dict(payload)

    assert len(restored.transitions) == 3
    assert restored.transitions[-1].evidence_ref == "ev-2"
    assert [t.to_state for t in restored.transitions] == [
        "pending", "approved", "executed",
    ]


def test_legacy_record_without_transitions_compatible():
    legacy = {
        "approvalId": "appr-old",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:abc",
        "parameters": {"material": "X"},
        "approver": "tester",
        "approvedAt": "2026-09-25T00:00:00+00:00",
        "expiresAt": "2099-01-01T00:00:00+00:00",
        "status": "pending",
        # no "transitions" key
    }
    restored = ApprovalRecord.from_dict(legacy)

    assert restored.transitions == ()
    assert restored.status == ApprovalState.pending


def test_transition_serialization_omits_empty_evidence():
    t = StateTransition(
        from_state="pending", to_state="approved", event="approved",
        timestamp="2026-09-25T00:00:00+00:00", actor="tester",
    )
    payload = t.to_dict()

    assert "evidenceRef" not in payload
    assert StateTransition.from_dict(payload).evidence_ref == ""
