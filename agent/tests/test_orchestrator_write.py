from __future__ import annotations

import json
from dataclasses import replace

from sap_nexus_agent import orchestrator
from sap_nexus_agent.approval import ApprovalState
from sap_nexus_agent.call_plan import create_call_plan
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.orchestrator import run_query


class StubWriteGateway:
    """Gateway double for the WRITE (PR create) path.

    execute returns ExecutionResult.from_dict so the orchestrator can read
    prNumber via execution.data (absorbed from the top-level payload field,
    per the ExecutionResult.from_dict extension). validate always succeeds.
    approve records the registered ApprovalRecord so tests can assert the
    Agent<->Gateway approval registration channel (Task 18).
    """

    def __init__(self, execute_payload: dict, *, approve_returns_empty: bool = False):
        self._execute_payload = execute_payload
        self._approve_returns_empty = approve_returns_empty
        self.validate_calls: list = []
        self.execute_calls: list = []
        self.approve_calls: list = []

    def validate(self, capability_id: str, parameters: dict[str, str]):
        self.validate_calls.append((capability_id, dict(parameters)))
        return ValidationResult(
            trace_id="trace-val",
            capability_id=capability_id,
            success=True,
            error_type="NONE",
            messages=[],
        )

    def approve(self, capability_id: str, approval_record):
        self.approve_calls.append((capability_id, approval_record))
        return "" if self._approve_returns_empty else approval_record.approval_id

    def execute(
        self,
        capability_id: str,
        parameters: dict[str, str],
        approval_id: str | None = None,
        parameter_snapshot_hash: str | None = None,
    ):
        self.execute_calls.append(
            (capability_id, dict(parameters), approval_id, parameter_snapshot_hash)
        )
        return ExecutionResult.from_dict(self._execute_payload)


def _approve_pending(pending, gateway):
    return orchestrator.continue_action(
        pending.call_plan,
        pending.validation_result,
        pending.approval_record,
        gateway,
        decision="approve",
    )


def test_pr_create_missing_params_returns_clarification():
    gateway = StubWriteGateway({})
    outcome = run_query("建个采购申请", gateway)
    assert outcome.status == "clarification"
    assert "material" in (outcome.missing_parameters or [])
    assert len(gateway.execute_calls) == 0


def test_pr_create_complete_request_waits_for_human_approval():
    gateway = StubWriteGateway({})

    outcome = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )

    assert outcome.status == "awaiting_approval"
    assert outcome.approval_record is not None
    assert outcome.approval_record.status is ApprovalState.pending
    assert gateway.approve_calls == []
    assert gateway.execute_calls == []


def test_pr_create_approval_record_is_not_partially_plan_aware():
    """Regression: the Gateway's ApprovalGuard/approve endpoint fail-closed rejects
    a record that sets registry_snapshot_id without also setting
    capability_version and approval_subject_hash (Java: hasCompletePlanBinding).
    The Agent does not yet compute the latter two, so it must leave all three
    blank (the fully-supported "not plan-aware" shape) rather than half-populate
    them and get rejected by the real Gateway.
    """
    gateway = StubWriteGateway({})

    outcome = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )

    assert outcome.approval_record is not None
    assert outcome.approval_record.registry_snapshot_id == ""
    assert outcome.approval_record.capability_version == ""
    assert outcome.approval_record.approval_subject_hash == ""


def test_pr_create_continuation_executes_only_after_external_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_TRACE_DIR", str(tmp_path))
    gateway = StubWriteGateway({
        "traceId": "trace-001",
        "capabilityId": "MM.PR.CreateDraft",
        "success": True,
        "prNumber": "0010001234",
        "commitStatus": "committed",
        "returnMessages": [],
        "durationMs": 150,
        "errorType": "NONE",
    })
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )

    outcome = orchestrator.continue_action(
        pending.call_plan,
        pending.validation_result,
        pending.approval_record,
        gateway,
        decision="approve",
    )

    assert outcome.status == "success"
    assert outcome.approval_record is not None
    assert outcome.approval_record.status is ApprovalState.executed
    assert len(gateway.approve_calls) == 1
    assert len(gateway.execute_calls) == 1
    assert gateway.execute_calls[0][1] == pending.approval_record.parameters


def test_pr_create_continuation_rejects_without_gateway_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_TRACE_DIR", str(tmp_path))
    gateway = StubWriteGateway({})
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )

    outcome = orchestrator.continue_action(
        pending.call_plan,
        pending.validation_result,
        pending.approval_record,
        gateway,
        decision="reject",
    )

    assert outcome.status == "rejected"
    assert outcome.approval_record is not None
    assert outcome.approval_record.status is ApprovalState.rejected
    assert gateway.approve_calls == []
    assert gateway.execute_calls == []


def test_pr_create_continuation_rejects_parameter_snapshot_mismatch():
    gateway = StubWriteGateway({})
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    changed_parameters = dict(pending.call_plan.parameters)
    changed_parameters["quantity"] = "999"
    changed_plan = create_call_plan(
        pending.call_plan.capability_id,
        changed_parameters,
        kind="Action",
    )

    outcome = orchestrator.continue_action(
        changed_plan,
        pending.validation_result,
        pending.approval_record,
        gateway,
        decision="approve",
    )

    assert outcome.status == "failure"
    assert outcome.error_type == "APPROVAL_VERSION_MISMATCH"
    assert gateway.approve_calls == []
    assert gateway.execute_calls == []


def test_pr_create_continuation_rejects_tampered_approval_parameters():
    gateway = StubWriteGateway({})
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    tampered_parameters = dict(pending.approval_record.parameters)
    tampered_parameters["quantity"] = "999"
    tampered_record = replace(
        pending.approval_record,
        parameters=tampered_parameters,
    )

    outcome = orchestrator.continue_action(
        pending.call_plan,
        pending.validation_result,
        tampered_record,
        gateway,
        decision="approve",
    )

    assert outcome.status == "failure"
    assert outcome.error_type == "APPROVAL_VERSION_MISMATCH"
    assert gateway.approve_calls == []
    assert gateway.execute_calls == []


def test_pr_create_continuation_rejects_unsuccessful_validation():
    gateway = StubWriteGateway({})
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    failed_validation = replace(
        pending.validation_result,
        success=False,
        error_type="INVALID_PARAMETER",
    )

    outcome = orchestrator.continue_action(
        pending.call_plan,
        failed_validation,
        pending.approval_record,
        gateway,
        decision="approve",
    )

    assert outcome.status == "failure"
    assert outcome.error_type == "APPROVAL_REQUIRED"
    assert gateway.approve_calls == []
    assert gateway.execute_calls == []


def test_pr_create_continuation_rejects_validation_capability_mismatch():
    gateway = StubWriteGateway({})
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    mismatched_validation = replace(
        pending.validation_result,
        capability_id="MM.Other.Write",
    )

    outcome = orchestrator.continue_action(
        pending.call_plan,
        mismatched_validation,
        pending.approval_record,
        gateway,
        decision="approve",
    )

    assert outcome.status == "failure"
    assert outcome.error_type == "APPROVAL_VERSION_MISMATCH"
    assert gateway.approve_calls == []
    assert gateway.execute_calls == []


def test_pr_create_success_returns_pr_number():
    execute_payload = {
        "traceId": "trace-001",
        "capabilityId": "MM.PR.CreateDraft",
        "success": True,
        "prNumber": "0010001234",
        "commitStatus": "committed",
        "returnMessages": [],
        "durationMs": 150,
        "errorType": "NONE",
    }
    gateway = StubWriteGateway(execute_payload)
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    outcome = _approve_pending(pending, gateway)
    assert outcome.status == "success"
    assert len(gateway.execute_calls) == 1
    capability_id, params, approval_id, _hash = gateway.execute_calls[0]
    assert capability_id == "MM.PR.CreateDraft"
    assert params["purchasing_group"] == "601"
    assert approval_id is not None
    assert approval_id.startswith("appr-")


def test_pr_create_sap_error_returns_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_TRACE_DIR", str(tmp_path))
    execute_payload = {
        "traceId": "trace-002",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "rolled_back",
        "returnMessages": [{"type": "E", "message": "Material not found"}],
        "durationMs": 80,
        "errorType": "SAP_BUSINESS_ERROR",
    }
    gateway = StubWriteGateway(execute_payload)
    pending = run_query(
        "给物料 INVALID 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    outcome = _approve_pending(pending, gateway)
    assert outcome.status == "failure"
    assert outcome.error_type == "SAP_BUSINESS_ERROR"
    events = [json.loads(line) for line in (tmp_path / "approval.jsonl").read_text().splitlines()]
    assert [event["toState"] for event in events] == ["pending", "approved"]


def test_pr_create_approval_required_returns_failure():
    execute_payload = {
        "traceId": "trace-003",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "none",
        "returnMessages": [],
        "durationMs": 1,
        "errorType": "APPROVAL_REQUIRED",
    }
    gateway = StubWriteGateway(execute_payload)
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    outcome = _approve_pending(pending, gateway)
    assert outcome.status == "failure"
    assert outcome.error_type == "APPROVAL_REQUIRED"


def test_pr_create_registers_approved_approval_with_gateway_before_execute(tmp_path, monkeypatch):
    """Task 18: Agent must register the approved ApprovalRecord with the Gateway
    so the fail-closed ApprovalGuard at execute entry can find it. The record
    must be transitioned pending -> approved before registration, and the same
    approvalId must be carried on the subsequent execute call.
    """
    monkeypatch.setenv("SAP_NEXUS_TRACE_DIR", str(tmp_path))
    execute_payload = {
        "traceId": "trace-001",
        "capabilityId": "MM.PR.CreateDraft",
        "success": True,
        "prNumber": "0010001234",
        "commitStatus": "committed",
        "returnMessages": [],
        "durationMs": 150,
        "errorType": "NONE",
    }
    gateway = StubWriteGateway(execute_payload)
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    outcome = _approve_pending(pending, gateway)
    assert outcome.status == "success"

    assert len(gateway.approve_calls) == 1, "orchestrator must register approval with Gateway"
    cap_id, registered_record = gateway.approve_calls[0]
    assert cap_id == "MM.PR.CreateDraft"
    assert registered_record.status == "approved", "record must be pending -> approved before registration"
    assert registered_record.parameter_snapshot_hash.startswith("sha256:")
    assert registered_record.parameters["purchasing_group"] == "601"
    assert registered_record.approval_id.startswith("appr-")

    events = [json.loads(line) for line in (tmp_path / "approval.jsonl").read_text().splitlines()]
    assert [event["toState"] for event in events] == ["pending", "approved", "executed"]

    assert len(gateway.execute_calls) == 1
    _, _, exec_approval_id, _ = gateway.execute_calls[0]
    assert exec_approval_id == registered_record.approval_id, (
        "execute must carry the same approvalId that was registered"
    )


def test_pr_create_stops_before_execute_when_gateway_rejects_approval_registration():
    """Regression: gateway.approve()'s return value was previously discarded, so a
    rejected registration (e.g. Gateway 403 on a missing/mismatched
    SAP_NEXUS_APPROVAL_TOKEN) silently fell through to execute() and surfaced a
    confusing APPROVAL_REQUIRED failure from the execute step instead of failing
    closed at registration.
    """
    gateway = StubWriteGateway({}, approve_returns_empty=True)
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    outcome = _approve_pending(pending, gateway)

    assert outcome.status == "failure"
    assert outcome.error_type == "APPROVAL_REGISTRATION_FAILED"
    assert gateway.execute_calls == [], "execute must not run when registration was not confirmed"


def test_pr_create_execute_carries_parameter_snapshot_hash_matching_registered_record():
    """Task 18 fix (CRITICAL-1): orchestrator must pass the registered record's
    parameterSnapshotHash to gateway.execute so the Gateway fail-closed
    ApprovalGuard can verify version match (guard check #3). Without it the guard
    rejects with APPROVAL_VERSION_MISMATCH even though the approval was registered.
    """
    execute_payload = {
        "traceId": "trace-001",
        "capabilityId": "MM.PR.CreateDraft",
        "success": True,
        "prNumber": "0010001234",
        "commitStatus": "committed",
        "returnMessages": [],
        "durationMs": 150,
        "errorType": "NONE",
    }
    gateway = StubWriteGateway(execute_payload)
    pending = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601",
        gateway,
    )
    outcome = _approve_pending(pending, gateway)
    assert outcome.status == "success"

    assert len(gateway.approve_calls) == 1
    _, registered_record = gateway.approve_calls[0]
    registered_hash = registered_record.parameter_snapshot_hash
    assert registered_hash.startswith("sha256:")

    assert len(gateway.execute_calls) == 1
    _, _, _, exec_hash = gateway.execute_calls[0]
    assert exec_hash == registered_hash, (
        "execute must carry the parameterSnapshotHash of the registered approval "
        "so the Gateway guard can verify version match (otherwise APPROVAL_VERSION_MISMATCH)"
    )
