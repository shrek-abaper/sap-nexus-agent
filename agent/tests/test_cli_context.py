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
