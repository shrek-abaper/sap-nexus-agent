from __future__ import annotations

import io
import json
import sys
from copy import deepcopy

import pytest

from sap_nexus_agent import cli
from sap_nexus_agent.call_plan import create_call_plan
from sap_nexus_agent.conversation_context import ReadExecutionBinding
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.governed_context import PLACEHOLDER_PRINCIPAL
from sap_nexus_agent.orchestrator import _default_planner_sources
from sap_nexus_agent.read_context import ConversationReadState, ReadContextFrame, SlotBinding


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
    snapshot, _sources = _default_planner_sources()
    turn_id = "turn-cli-batch"
    slots = {
        name: SlotBinding(
            name,
            value,
            (value,),
            "RESOLVED",
            "EXPLICIT",
            turn_id,
            None,
            (),
        )
        for name, value in {
            "material": "DEMOA2",
            "plant": "5200",
        }.items()
    }
    frame = ReadContextFrame(
        "frame-cli-batch",
        "MM.Inventory.GetAvailability",
        slots,
        "READY",
        turn_id,
        turn_id,
        snapshot.snapshot_id,
        "1",
    )
    persisted_state = ConversationReadState(frame, None, 2)
    call_plan = create_call_plan(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA2", "plant": "5200", "unit": "EA"},
        kind="Function",
    )
    binding = ReadExecutionBinding.create(
        turn_id=turn_id,
        principal_id=PLACEHOLDER_PRINCIPAL.principal_id,
        call_plan=call_plan,
        read_state=persisted_state,
        executor_binding_id="sap.mm.inventory.md04-stock-req-list",
    )
    return {
        "callPlan": call_plan.to_dict(),
        "combinations": [
            {"material": "DEMOA2", "plant": "5200", "unit": "EA"},
            {"material": "DEMOA2", "plant": "1000", "unit": "EA"},
        ],
        "readExecutionBinding": binding.to_dict(),
        "persistedReadState": persisted_state.to_dict(),
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


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("missing binding", lambda payload: payload.pop("readExecutionBinding")),
        (
            "capability version drift",
            lambda payload: payload["readExecutionBinding"].__setitem__(
                "capabilityVersion", "999"
            ),
        ),
        (
            "executor binding drift",
            lambda payload: payload["readExecutionBinding"].__setitem__(
                "executorBindingId", "forged-binding"
            ),
        ),
        (
            "principal drift",
            lambda payload: payload["readExecutionBinding"].__setitem__(
                "principalId", "forged-principal"
            ),
        ),
        (
            "snapshot drift",
            lambda payload: payload["readExecutionBinding"].__setitem__(
                "registrySnapshotId", "forged-snapshot"
            ),
        ),
        (
            "persisted state drift",
            lambda payload: payload["persistedReadState"].__setitem__(
                "stateVersion", 3
            ),
        ),
        (
            "invalid combination parameter",
            lambda payload: payload["combinations"][0].__setitem__(
                "plant", "工厂"
            ),
        ),
        (
            "missing required combination parameter",
            lambda payload: payload["combinations"][0].pop("plant"),
        ),
    ],
)
def test_cli_batch_preflight_rejects_forged_authority_before_gateway_construction(
    case, mutate, monkeypatch, capsys
):
    payload = deepcopy(_batch_payload())
    mutate(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    def forbidden_gateway(_url):
        raise AssertionError(f"{case} constructed GatewayClient")

    monkeypatch.setattr(cli, "GatewayClient", forbidden_gateway)

    result = cli.main([
        "--continue-batch",
        "--gateway-url",
        "http://gateway.test",
        "--json",
    ])

    assert result == 2
    assert json.loads(capsys.readouterr().out)["errorType"] == (
        "BATCH_EXECUTION_BINDING_MISMATCH"
    )
