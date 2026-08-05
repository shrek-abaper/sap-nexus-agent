from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from sap_nexus_agent.approval import (
    ApprovalRecord,
    ApprovalState,
    InvalidApprovalTransition,
    approve,
    compute_parameter_hash,
    create_approval_record,
    is_expired,
    mark_executed,
    reject,
)


@pytest.fixture(autouse=True)
def _isolate_trace_dir(tmp_path, monkeypatch):
    """Route JSONL trace writes to a per-test tmp dir; never touch real runtime/traces/."""
    monkeypatch.setenv("SAP_NEXUS_TRACE_DIR", str(tmp_path / "traces"))


def test_compute_parameter_hash_is_deterministic():
    params = {"material": "M001", "plant": "1000", "quantity": "10"}
    hash1 = compute_parameter_hash(params)
    hash2 = compute_parameter_hash(params)
    assert hash1 == hash2
    assert hash1.startswith("sha256:")


def test_compute_parameter_hash_uses_compact_sorted_json_contract():
    assert compute_parameter_hash({"b": "2", "a": "1"}) == (
        "sha256:21f76dfbfe6dfe21f762080ef484112cf2952974cef30741fd1931e1c6d92112"
    )


def test_compute_parameter_hash_differs_on_change():
    base = {"material": "M001", "plant": "1000"}
    changed = {"material": "M002", "plant": "1000"}
    assert compute_parameter_hash(base) != compute_parameter_hash(changed)


def test_create_approval_record_starts_pending():
    params = {"material": "M001", "plant": "1000", "quantity": "10", "unit": "EA", "delivery_date": "2026-08-01"}
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters=params,
        approver="user@example.com",
        ttl_seconds=600,
    )
    assert record.capability_id == "MM.PR.CreateDraft"
    assert record.parameter_snapshot_hash.startswith("sha256:")
    assert record.status == ApprovalState.pending
    assert record.approver == "user@example.com"


def test_approval_record_round_trips_workbench_payload():
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001", "plant": "1000"},
        approver="user@example.com",
    )

    restored = ApprovalRecord.from_dict(record.to_dict())

    assert restored == record


def test_is_expired_true_after_ttl():
    now = datetime(2026, 7, 16, 10, 11, 0, tzinfo=timezone.utc)
    record = ApprovalRecord(
        approval_id="appr-001",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:abc",
        parameters={"material": "M001"},
        approver="user",
        approved_at=datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 16, 10, 10, 0, tzinfo=timezone.utc),
        status=ApprovalState.approved,
    )
    assert is_expired(record, now) is True


def test_is_expired_false_within_ttl():
    now = datetime(2026, 7, 16, 10, 5, 0, tzinfo=timezone.utc)
    record = ApprovalRecord(
        approval_id="appr-001",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:abc",
        parameters={"material": "M001"},
        approver="user",
        approved_at=datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 16, 10, 10, 0, tzinfo=timezone.utc),
        status=ApprovalState.approved,
    )
    assert is_expired(record, now) is False


# --- State machine transition API ------------------------------------------


def test_approve_transitions_pending_to_approved():
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    approved_rec = approve(record)
    assert approved_rec.status == ApprovalState.approved
    assert approved_rec.approval_id == record.approval_id
    assert approved_rec.approved_at >= record.approved_at


def test_mark_executed_transitions_approved_to_executed():
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    approved_rec = approve(record)
    executed_rec = mark_executed(approved_rec)
    assert executed_rec.status == ApprovalState.executed
    assert executed_rec.approval_id == record.approval_id


def test_reject_transitions_pending_to_rejected():
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    rejected_rec = reject(record)
    assert rejected_rec.status == ApprovalState.rejected
    assert rejected_rec.approval_id == record.approval_id


def test_reject_transitions_approved_to_rejected():
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    approved_rec = approve(record)
    rejected_rec = reject(approved_rec)
    assert rejected_rec.status == ApprovalState.rejected


def test_approve_rejected_raises_invalid_transition():
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    rejected_rec = reject(record)
    with pytest.raises(InvalidApprovalTransition):
        approve(rejected_rec)


def test_mark_executed_pending_raises_invalid_transition():
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    with pytest.raises(InvalidApprovalTransition):
        mark_executed(record)


def test_mark_executed_rejected_raises_invalid_transition():
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    rejected_rec = reject(record)
    with pytest.raises(InvalidApprovalTransition):
        mark_executed(rejected_rec)


def test_approve_already_approved_raises_invalid_transition():
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    approved_rec = approve(record)
    with pytest.raises(InvalidApprovalTransition):
        approve(approved_rec)


# --- JSONL trace persistence -----------------------------------------------


def test_create_writes_jsonl_trace_event(tmp_path):
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001", "plant": "1000"},
        approver="user@example.com",
    )
    trace_file = tmp_path / "traces" / "approval.jsonl"
    assert trace_file.exists()
    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["approvalId"] == record.approval_id
    assert event["capabilityId"] == "MM.PR.CreateDraft"
    assert event["parameterSnapshotHash"] == record.parameter_snapshot_hash
    assert event["approver"] == "user@example.com"
    assert event["fromState"] is None
    assert event["toState"] == "pending"
    assert "traceId" in event and event["traceId"]
    assert "timestamp" in event and event["timestamp"]


def test_each_transition_appends_jsonl_event(tmp_path):
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    approved_rec = approve(record)
    mark_executed(approved_rec)
    trace_file = tmp_path / "traces" / "approval.jsonl"
    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    states = [json.loads(line)["toState"] for line in lines]
    assert states == ["pending", "approved", "executed"]
    transitions = [(json.loads(line)["fromState"], json.loads(line)["toState"]) for line in lines]
    assert transitions[0] == (None, "pending")
    assert transitions[1] == ("pending", "approved")
    assert transitions[2] == ("approved", "executed")


def test_trace_event_omits_sensitive_parameter_values(tmp_path):
    sensitive_params = {
        "material": "M001",
        "plant": "1000",
        "sap_password": "super-secret-credential",
        "auth_token": "bearer-abc-123",
    }
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters=sensitive_params,
        approver="user@example.com",
    )
    trace_file = tmp_path / "traces" / "approval.jsonl"
    raw = trace_file.read_text(encoding="utf-8")
    assert "super-secret-credential" not in raw
    assert "bearer-abc-123" not in raw
    event = json.loads(raw.strip())
    summary = event["parametersSummary"]
    assert set(summary["keys"]) == {"material", "plant", "sap_password", "auth_token"}
    assert summary["count"] == 4
    assert "parameters" not in event


def test_trace_dir_created_when_missing(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested" / "traces"
    monkeypatch.setenv("SAP_NEXUS_TRACE_DIR", str(nested))
    create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    assert (nested / "approval.jsonl").exists()


# --- TTL environment variable ----------------------------------------------


def test_ttl_defaults_to_600_when_unset(monkeypatch):
    monkeypatch.delenv("SAP_NEXUS_APPROVAL_TTL_SECONDS", raising=False)
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    delta = record.expires_at - record.approved_at
    assert delta == timedelta(seconds=600)


def test_ttl_reads_env_when_param_absent(monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_APPROVAL_TTL_SECONDS", "120")
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    delta = record.expires_at - record.approved_at
    assert delta == timedelta(seconds=120)


def test_ttl_param_overrides_env(monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_APPROVAL_TTL_SECONDS", "120")
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
        ttl_seconds=300,
    )
    delta = record.expires_at - record.approved_at
    assert delta == timedelta(seconds=300)


def test_ttl_falls_back_to_default_on_invalid_env(monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_APPROVAL_TTL_SECONDS", "not-a-number")
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M001"},
        approver="user@example.com",
    )
    delta = record.expires_at - record.approved_at
    assert delta == timedelta(seconds=600)


# ---- Task 7: ApprovalRecord registry_snapshot_id ----


def test_approval_record_has_registry_snapshot_id_field():
    from sap_nexus_agent.approval import ApprovalRecord, ApprovalState
    from datetime import datetime, timezone

    record = ApprovalRecord(
        approval_id="appr-1",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:x",
        parameters={"material": "M1"},
        approver="user",
        approved_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
        status=ApprovalState.pending,
    )
    assert record.registry_snapshot_id == ""


def test_approval_record_to_dict_includes_registry_snapshot_id():
    from sap_nexus_agent.approval import ApprovalRecord, ApprovalState
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    record = ApprovalRecord(
        approval_id="appr-1",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:x",
        parameters={"material": "M1"},
        approver="user",
        approved_at=now,
        expires_at=now,
        status=ApprovalState.pending,
        registry_snapshot_id="sha256:snap-1",
    )
    d = record.to_dict()
    assert d["registrySnapshotId"] == "sha256:snap-1"


def test_approval_record_from_dict_backward_compat_without_field():
    from sap_nexus_agent.approval import ApprovalRecord

    payload = {
        "approvalId": "appr-1",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:x",
        "parameters": {"material": "M1"},
        "approver": "user",
        "approvedAt": "2026-01-01T00:00:00+00:00",
        "expiresAt": "2026-01-01T00:10:00+00:00",
        "status": "pending",
    }
    record = ApprovalRecord.from_dict(payload)
    assert record.registry_snapshot_id == ""


def test_approval_record_from_dict_reads_registry_snapshot_id():
    from sap_nexus_agent.approval import ApprovalRecord

    payload = {
        "approvalId": "appr-1",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:x",
        "parameters": {},
        "approver": "user",
        "approvedAt": "2026-01-01T00:00:00+00:00",
        "expiresAt": "2026-01-01T00:10:00+00:00",
        "status": "pending",
        "registrySnapshotId": "sha256:snap-2",
    }
    record = ApprovalRecord.from_dict(payload)
    assert record.registry_snapshot_id == "sha256:snap-2"


def test_create_approval_record_accepts_registry_snapshot_id():
    from sap_nexus_agent.approval import create_approval_record

    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters={"material": "M1"},
        approver="user",
        registry_snapshot_id="sha256:snap-3",
    )
    assert record.registry_snapshot_id == "sha256:snap-3"


def test_approval_record_round_trips_complete_plan_aware_gateway_bindings():
    now = datetime(2026, 8, 5, 8, 0, 0, tzinfo=timezone.utc)
    record = ApprovalRecord(
        approval_id="appr-plan-21",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:parameters",
        parameters={"material": "M001"},
        approver="run-owner",
        approved_at=now,
        expires_at=now + timedelta(minutes=10),
        status=ApprovalState.approved,
        registry_snapshot_id="snapshot-21",
        capability_version="2.1.0",
        approval_subject_hash="sha256:subject-21",
    )

    restored = ApprovalRecord.from_dict(record.to_dict())

    assert restored == record
    assert restored.to_dict() | {} == {
        "approvalId": "appr-plan-21",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:parameters",
        "parameters": {"material": "M001"},
        "approver": "run-owner",
        "approvedAt": "2026-08-05T08:00:00+00:00",
        "expiresAt": "2026-08-05T08:10:00+00:00",
        "status": "approved",
        "registrySnapshotId": "snapshot-21",
        "capabilityVersion": "2.1.0",
        "approvalSubjectHash": "sha256:subject-21",
    }


def test_approval_record_legacy_payload_defaults_new_plan_bindings_to_empty():
    payload = {
        "approvalId": "appr-legacy",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:parameters",
        "parameters": {"material": "M001"},
        "approver": "run-owner",
        "approvedAt": "2026-08-05T08:00:00+00:00",
        "expiresAt": "2026-08-05T08:10:00+00:00",
        "status": "approved",
    }

    restored = ApprovalRecord.from_dict(payload)

    assert restored.capability_version == ""
    assert restored.approval_subject_hash == ""
