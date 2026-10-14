"""ModelGoalInterpreter: prompt confinement and bounded draft generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sap_nexus_agent.ontology_planning.model_interpreter import (
    ModelGoalInterpreter,
    ModelInterpreterError,
    build_system_prompt,
)
from sap_nexus_agent.ontology_planning.release import pin_release

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeLlmClient:
    def __init__(self, payloads):
        self._payloads = payloads
        self.calls: list[dict] = []

    def chat_json(self, messages, *, temperature=0.0, max_tokens=0):
        index = min(len(self.calls), len(self._payloads) - 1)
        self.calls.append({"messages": messages, "temperature": temperature})
        payload = self._payloads[index]
        if isinstance(payload, Exception):
            raise payload
        return payload


@pytest.fixture(scope="module")
def pinned():
    return pin_release(REPO_ROOT)


def test_prompt_confinement(pinned):
    prompt = build_system_prompt(pinned)
    assert "BAPI_" not in prompt
    assert "http" not in prompt.lower()
    for operator in ("select_fields", "filter_eq", "group_sum", "compare"):
        assert operator in prompt
    assert "sapnexus:PurchaseOrderSupplyFact" in prompt
    assert "deliveryDate" not in prompt  # non-existent fields never advertised
    assert "availableQuantity" in prompt


def test_interpreter_returns_valid_draft(pinned):
    draft_doc = (
        REPO_ROOT / "evals/ontology-read-analysis/drafts/q1-stock-and-unit.json"
    ).read_text()
    import json

    client = FakeLlmClient([json.loads(draft_doc)])
    interpreter = ModelGoalInterpreter(pinned, client=client)
    request = {"utterance": "DEMOA2 在 1000 工厂的库存和基本单位"}
    draft = interpreter.interpret(request)
    assert draft["requestedFacts"][0]["factTypeId"] == "sapnexus:InventoryAvailabilityFact"
    assert interpreter.call_count == 1
    assert client.calls[0]["temperature"] == 0.0


def test_interpreter_passes_feedback_on_repair(pinned):
    import json

    q1 = json.loads((REPO_ROOT / "evals/ontology-read-analysis/drafts/q1-stock-and-unit.json").read_text())
    client = FakeLlmClient([q1])
    interpreter = ModelGoalInterpreter(pinned, client=client)
    interpreter.interpret({"utterance": "stock"})  # initial
    interpreter.interpret(
        {"utterance": "stock"},
        feedback=[{"path": "$", "code": "DRAFT_SCHEMA_INVALID", "message": "missing required keys"}],
    )
    assert interpreter.call_count == 2
    second_user_message = client.calls[1]["messages"][-1]["content"]
    assert "DRAFT_SCHEMA_INVALID" in second_user_message


def test_interpreter_rejects_non_object_and_non_json(pinned):
    client = FakeLlmClient([RuntimeError("connection failed")])
    interpreter = ModelGoalInterpreter(pinned, client=client)
    with pytest.raises(ModelInterpreterError):
        interpreter.interpret({"utterance": "x"})


def test_pipeline_rejects_technical_model_draft(pinned):
    import json
    from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
    from sap_nexus_agent.ontology_planning.draft_pipeline import prepare_draft

    bad = json.loads((REPO_ROOT / "evals/ontology-read-analysis/drafts/injection-rfc.json").read_text())

    class OneShot:
        call_count = 0
        def interpret(self, request, vocabulary=None, feedback=None):
            self.call_count += 1
            return bad

    interpreter = OneShot()
    sources = load_semantic_sources(REPO_ROOT)
    _draft, terminal = prepare_draft(
        {"interpreter": "model", "utterance": "x"},
        sources, pinned, REPO_ROOT / "evals/ontology-read-analysis",
        interpreter_instance=interpreter, live=True,
    )
    assert terminal["status"] == "rejected"
    assert interpreter.call_count == 2  # one repair attempt, then rejected
