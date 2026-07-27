from __future__ import annotations

import io
import json
import sys

from sap_nexus_agent import cli
from sap_nexus_agent.call_plan import create_call_plan
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult


class StubBatchGateway:
    def __init__(self):
        self.validate_calls = []
        self.execute_calls = []

    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, dict(parameters)))
        return ValidationResult(
            trace_id="trace-validate",
            capability_id=capability_id,
            success=True,
            error_type="NONE",
            messages=[],
        )

    def execute(self, capability_id, parameters, approval_id=None, parameter_snapshot_hash=None):
        self.execute_calls.append((capability_id, dict(parameters)))
        plant = parameters.get("plant", "")
        return ExecutionResult.from_dict({
            "traceId": "trace-execute",
            "capabilityId": capability_id,
            "success": True,
            "executor": {"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
            "returnMessages": [],
            "data": {
                "material": parameters.get("material", ""),
                "plant": plant,
                "availableQuantity": 176 if plant == "5200" else 0,
                "unit": "EA",
            },
            "durationMs": 12,
            "errorType": "NONE",
        })


def _batch_payload():
    call_plan = create_call_plan(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA2", "plant": "5200"},
        kind="Function",
    )
    return {
        "callPlan": call_plan.to_dict(),
        "combinations": [
            {"material": "DEMOA2", "plant": "5200"},
            {"material": "DEMOA2", "plant": "1000"},
        ],
    }


def test_cli_continues_batch_from_stdin(monkeypatch, capsys):
    gateway = StubBatchGateway()
    monkeypatch.setattr(cli, "GatewayClient", lambda _url: gateway)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_batch_payload())))

    result = cli.main([
        "--continue-batch",
        "--gateway-url",
        "http://gateway.test",
        "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["status"] == "success"
    assert len(gateway.execute_calls) == 2
    assert payload["responseText"] != ""


def test_cli_rejects_missing_batch_payload(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    result = cli.main([
        "--continue-batch",
        "--gateway-url",
        "http://gateway.test",
        "--json",
    ])

    assert result != 0
