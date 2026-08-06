import io
import json
from unittest.mock import patch

import pytest

from sap_nexus_agent.cli import main


def test_cli_context_mode_passes_context_to_run_query(capsys, monkeypatch):
    """--context 从 stdin 读 ConversationContext JSON 并传入 run_query。"""
    context_payload = {
        "lastContext": {
            "capabilityId": "MM.Inventory.GetAvailability",
            "parameters": {"material": "DEMOA2"},
            "missingParameters": ["plant"],
            "decisionType": "CLARIFY",
        },
        "history": None,
    }
    fake_stdin = io.StringIO(json.dumps(context_payload))
    monkeypatch.setattr("sys.stdin", fake_stdin)

    captured_context = {}

    def fake_run_query(text, gateway, *, intent_adapter=None, context=None, **kwargs):
        captured_context["text"] = text
        captured_context["context"] = context
        from sap_nexus_agent.orchestrator import AgentOutcome
        return AgentOutcome(status="clarification", message="请提供工厂", response_text="请提供工厂")

    monkeypatch.setattr("sap_nexus_agent.cli.run_query", fake_run_query)
    monkeypatch.setattr("sap_nexus_agent.cli.GatewayClient", lambda url: object())

    exit_code = main(["1000", "--context", "--gateway-url", "http://localhost:8080", "--json"])
    assert exit_code == 0
    assert captured_context["text"] == "1000"
    assert captured_context["context"] is not None
    assert captured_context["context"].last_context.capability_id == "MM.Inventory.GetAvailability"
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "clarification"


def test_cli_context_invalid_json_returns_failure(capsys, monkeypatch):
    fake_stdin = io.StringIO("not-json")
    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sap_nexus_agent.cli.GatewayClient", lambda url: object())
    exit_code = main(["1000", "--context", "--json"])
    assert exit_code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["errorType"] == "INVALID_CONTEXT_PAYLOAD"


def test_cli_context_non_dict_json_returns_invalid_payload(capsys, monkeypatch):
    """Valid JSON that is not a dict (list/string/number) -> INVALID_CONTEXT_PAYLOAD, not AttributeError traceback."""
    fake_stdin = io.StringIO(json.dumps([1, 2, 3]))
    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sap_nexus_agent.cli.GatewayClient", lambda url: object())
    exit_code = main(["1000", "--context", "--json"])
    assert exit_code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["errorType"] == "INVALID_CONTEXT_PAYLOAD"


def test_cli_context_without_query_returns_error(capsys, monkeypatch):
    """--context without a positional query must exit with an error, not crash in parse_intent."""
    context_payload = {"lastContext": None, "history": None}
    fake_stdin = io.StringIO(json.dumps(context_payload))
    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sap_nexus_agent.cli.GatewayClient", lambda url: object())
    with pytest.raises(SystemExit) as exc_info:
        main(["--context", "--gateway-url", "http://localhost:8080"])
    # argparse error() exits with status 2
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "query is required" in err


def test_cli_without_context_backward_compatible(capsys, monkeypatch):
    """无 --context 时 context=None，行为不变。"""
    captured = {}

    def fake_run_query(text, gateway, *, intent_adapter=None, context=None, **kwargs):
        captured["context"] = context
        from sap_nexus_agent.orchestrator import AgentOutcome
        return AgentOutcome(status="success", response_text="ok")

    monkeypatch.setattr("sap_nexus_agent.cli.run_query", fake_run_query)
    monkeypatch.setattr("sap_nexus_agent.cli.GatewayClient", lambda url: object())
    exit_code = main(["库存 DEMOA2 1000", "--json"])
    assert exit_code == 0
    assert captured["context"] is None


def test_cli_resolve_read_turn_never_constructs_gateway(capsys, monkeypatch):
    from sap_nexus_agent.orchestrator import AgentOutcome

    context_payload = {
        "lastContext": None,
        "history": None,
        "schemaVersion": 2,
        "readState": {
            "activeFrame": None,
            "pendingInteraction": None,
            "stateVersion": 0,
            "recentFrames": [],
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(context_payload)))
    captured = {}

    def fake_resolve(text, **kwargs):
        captured.update(text=text, **kwargs)
        return AgentOutcome(
            status="clarification",
            response_text="请提供物料",
            turn_id=kwargs["turn_id"],
            frame_id="frame-cli",
            state_version=1,
            registry_snapshot_id="snapshot-cli",
        )

    marker = object()
    monkeypatch.setattr(
        "sap_nexus_agent.cli._build_adapter_and_principal",
        lambda _mode: (marker, marker, marker, marker),
    )
    monkeypatch.setattr("sap_nexus_agent.cli.resolve_read_turn", fake_resolve)

    def forbidden_gateway(_url):
        raise AssertionError("resolve-read-turn constructed GatewayClient")

    monkeypatch.setattr("sap_nexus_agent.cli.GatewayClient", forbidden_gateway)

    exit_code = main([
        "查库存",
        "--resolve-read-turn",
        "--turn-id",
        "turn-cli-1",
        "--json",
    ])

    assert exit_code == 0
    assert captured["turn_id"] == "turn-cli-1"
    assert captured["context"].read_state.state_version == 0
    output = json.loads(capsys.readouterr().out)
    assert output["turnId"] == "turn-cli-1"


def test_cli_continue_read_binding_mismatch_has_no_gateway(capsys, monkeypatch):
    from sap_nexus_agent.call_plan import create_call_plan
    from sap_nexus_agent.conversation_context import ReadExecutionBinding
    from sap_nexus_agent.read_context import ConversationReadState, ReadContextFrame, SlotBinding

    slot = SlotBinding(
        "material", "DEMOA2", ("DEMOA2",), "RESOLVED", "EXPLICIT",
        "turn-cli", None, (),
    )
    frame = ReadContextFrame(
        "frame-cli", "MM.Inventory.GetAvailability", {"material": slot}, "READY",
        "turn-cli", "turn-cli", "snapshot-cli", "1",
    )
    state = ConversationReadState(frame, None, 1)
    plan = create_call_plan("MM.Inventory.GetAvailability", {"material": "DEMOA2"})
    binding = ReadExecutionBinding.create(
        turn_id="turn-cli",
        principal_id="local-user-0001",
        call_plan=plan,
        read_state=state,
        executor_binding_id="sap.mm.inventory.md04-stock-req-list",
    ).to_dict()
    binding["turnId"] = "turn-tampered"
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"callPlan": plan.to_dict(), "binding": binding})),
    )

    def forbidden_gateway(_url):
        raise AssertionError("binding mismatch constructed GatewayClient")

    monkeypatch.setattr("sap_nexus_agent.cli.GatewayClient", forbidden_gateway)

    exit_code = main(["--continue-read", "--json"])

    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["errorType"] == "READ_EXECUTION_BINDING_MISMATCH"


def test_cli_continue_read_semantic_preflight_finishes_before_gateway_construction(
    capsys, monkeypatch
):
    from sap_nexus_agent.call_plan import create_call_plan
    from sap_nexus_agent.conversation_context import ReadExecutionBinding
    from sap_nexus_agent.orchestrator import _default_planner_sources
    from sap_nexus_agent.read_context import ConversationReadState, ReadContextFrame, SlotBinding

    snapshot, _sources = _default_planner_sources()
    material = SlotBinding(
        "material", "DEMOA2", ("DEMOA2",), "RESOLVED", "EXPLICIT",
        "turn-cli-semantic", None, (),
    )
    frame = ReadContextFrame(
        "frame-cli-semantic", "MM.Inventory.GetAvailability", {"material": material}, "READY",
        "turn-cli-semantic", "turn-cli-semantic", snapshot.snapshot_id, "1",
    )
    state = ConversationReadState(frame, None, 1)
    plan = create_call_plan(
        "MM.Inventory.GetAvailability", {"material": "DEMOA2", "unit": "EA"}
    )
    binding = ReadExecutionBinding.create(
        turn_id="turn-cli-semantic",
        principal_id="local-user-0001",
        call_plan=plan,
        read_state=state,
        executor_binding_id="sap.mm.inventory.md04-stock-req-list",
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({
            "callPlan": plan.to_dict(),
            "binding": binding.to_dict(),
            "persistedReadState": state.to_dict(),
        })),
    )

    def forbidden_gateway(_url):
        raise AssertionError("semantic mismatch constructed GatewayClient")

    monkeypatch.setattr("sap_nexus_agent.cli.GatewayClient", forbidden_gateway)

    exit_code = main(["--continue-read", "--json"])

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["errorType"] == (
        "READ_EXECUTION_BINDING_MISMATCH"
    )
