from __future__ import annotations

import io
import json
import sys

from sap_nexus_agent import cli
from sap_nexus_agent.approval import create_approval_record
from sap_nexus_agent.call_plan import create_call_plan
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult


class StubGateway:
    def __init__(self):
        self.approve_calls = []
        self.execute_calls = []

    def validate(self, capability_id, parameters):
        return ValidationResult(
            trace_id="trace-validate",
            capability_id=capability_id,
            success=True,
            error_type="NONE",
            messages=[],
        )

    def approve(self, capability_id, approval_record):
        self.approve_calls.append((capability_id, approval_record))
        return approval_record.approval_id

    def execute(
        self,
        capability_id,
        parameters,
        approval_id=None,
        parameter_snapshot_hash=None,
    ):
        self.execute_calls.append(
            (capability_id, dict(parameters), approval_id, parameter_snapshot_hash)
        )
        return ExecutionResult.from_dict({
            "traceId": "trace-execute",
            "capabilityId": capability_id,
            "success": True,
            "prNumber": "10137471",
            "commitStatus": "committed",
            "returnMessages": [],
            "durationMs": 10,
            "errorType": "NONE",
        })


def _pending_payload():
    parameters = {
        "material": "M001",
        "plant": "1000",
        "quantity": "10",
        "unit": "EA",
        "delivery_date": "2026-08-01",
        "purchasing_group": "601",
    }
    call_plan = create_call_plan("MM.PR.CreateDraft", parameters, kind="Action")
    approval = create_approval_record(
        capability_id=call_plan.capability_id,
        parameters=call_plan.parameters,
        approver="user",
    )
    validation = ValidationResult(
        trace_id="trace-validate",
        capability_id=call_plan.capability_id,
        success=True,
        error_type="NONE",
        messages=[],
    )
    return {
        "decision": "approve",
        "callPlan": call_plan.to_dict(),
        "validationResult": {
            "traceId": validation.trace_id,
            "capabilityId": validation.capability_id,
            "success": validation.success,
            "errorType": validation.error_type,
            "messages": validation.messages,
        },
        "approvalRecord": approval.to_dict(),
    }


def test_cli_continues_external_approval_from_stdin(monkeypatch, capsys):
    gateway = StubGateway()
    monkeypatch.setattr(cli, "GatewayClient", lambda _url: gateway)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_pending_payload())))

    result = cli.main([
        "--continue-action",
        "--gateway-url",
        "http://gateway.test",
        "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["status"] == "success"
    assert payload["approvalRecord"]["status"] == "executed"
    assert len(gateway.approve_calls) == 1
    assert len(gateway.execute_calls) == 1


def test_cli_rejects_missing_continuation_payload(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    result = cli.main([
        "--continue-action",
        "--gateway-url",
        "http://gateway.test",
        "--json",
    ])

    assert result != 0


def test_cli_treats_pending_action_as_successful_handoff(monkeypatch, capsys):
    gateway = StubGateway()
    monkeypatch.setattr(cli, "GatewayClient", lambda _url: gateway)

    result = cli.main([
        "给物料 M001 工厂 1000 建 10 EA 采购申请 交货 2026-08-01 采购组 601",
        "--intent-mode",
        "rule",
        "--gateway-url",
        "http://gateway.test",
        "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["status"] == "awaiting_approval"
    assert gateway.execute_calls == []
