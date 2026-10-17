"""Shared draft pipeline: selection, precheck, validation, one repair."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sap_nexus_agent.ontology_planning.draft_pipeline import prepare_draft
from sap_nexus_agent.ontology_planning.release import pin_release
from sap_nexus_agent.ontology_planning.interpreter import FakeGoalInterpreter
from sap_nexus_agent.semantic_planning.loader import load_semantic_sources

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def world():
    pinned = pin_release(REPO_ROOT)
    sources = load_semantic_sources(REPO_ROOT)
    return pinned, sources


def _request(case_id="q1-stock-and-unit", **extra):
    request = {
        "schemaVersion": 1,
        "caseId": case_id,
        "interpreter": "fake",
        "slots": {"material": "DEMOA2", "plant": "1000"},
    }
    request.update(extra)
    return request


def test_fake_draft_passes_unchanged(world):
    pinned, sources = world
    draft, terminal = prepare_draft(_request(), sources, pinned, REPO_ROOT / "evals/ontology-read-analysis")
    assert terminal is None
    assert draft["requestedFacts"][0]["factTypeId"] == "sapnexus:InventoryAvailabilityFact"


class _StubInterpreter:
    def __init__(self, document):
        self._document = document

    def interpret(self, request, vocabulary, feedback=None):
        return self._document


def test_model_draft_is_supplemented_with_server_slots(world):
    pinned, sources = world
    document = json.loads(
        (REPO_ROOT / "evals/ontology-read-analysis/drafts/q1-stock-and-unit.json").read_text()
    )
    # The model omitted the plant selector entirely (the utterance named no plant).
    for fact in document["requestedFacts"]:
        fact["objectSelectors"] = [
            selector for selector in fact["objectSelectors"] if selector["key"] != "plant"
        ]
    draft, terminal = prepare_draft(
        _request(interpreter="model", utterance="看下库存", slots={"material": "DEMOA2", "plant": "5260"}),
        sources,
        pinned,
        REPO_ROOT / "evals/ontology-read-analysis",
        interpreter_instance=_StubInterpreter(document),
        live=True,
    )
    assert terminal is None
    for fact in draft["requestedFacts"]:
        keys = {selector["key"] for selector in fact["objectSelectors"]}
        assert "plant" in keys
        plant = next(selector for selector in fact["objectSelectors"] if selector["key"] == "plant")
        assert plant["value"] == "5260"


def test_model_interpreter_requires_live_flag(world, monkeypatch):
    pinned, sources = world
    # Explicit 0 wins over the .env default (dotenv never overrides set vars).
    monkeypatch.setenv("SAP_NEXUS_LLM_LIVE", "0")
    draft, terminal = prepare_draft(
        _request(interpreter="model", utterance="stock please"),
        sources, pinned, REPO_ROOT / "evals/ontology-read-analysis",
    )
    assert draft is None
    assert terminal["status"] == "rejected"
    assert "MODEL_INTERPRETER_NOT_AUTHORIZED" in terminal["reasons"]


class ScriptedInterpreter:
    def __init__(self, documents):
        self._documents = documents
        self.call_count = 0
        self.feedback_seen = []

    def interpret(self, request, vocabulary=None, feedback=None):
        index = min(self.call_count, len(self._documents) - 1)
        self.call_count += 1
        if feedback is not None:
            self.feedback_seen.append(feedback)
        return self._documents[index]


def test_structural_repair_round_recovers(world):
    pinned, sources = world
    good = json.loads(
        (REPO_ROOT / "evals/ontology-read-analysis/drafts/q1-stock-and-unit.json").read_text()
    )
    bad = {"unexpected": True}  # schema-level failure the model can repair
    interpreter = ScriptedInterpreter([bad, good])
    draft, terminal = prepare_draft(
        _request(interpreter="model", utterance="stock"),
        sources, pinned, REPO_ROOT / "evals/ontology-read-analysis",
        interpreter_instance=interpreter,
        live=True,
    )
    assert terminal is None
    assert interpreter.call_count == 2
    assert interpreter.feedback_seen, "repair must feed issues back"


def test_unknown_field_is_first_round_semantic_gap_without_repair(world):
    pinned, sources = world
    good = json.loads(
        (REPO_ROOT / "evals/ontology-read-analysis/drafts/q1-stock-and-unit.json").read_text()
    )
    bad = json.loads(json.dumps(good))
    bad["requestedFacts"][0]["fields"] = ["deliveryDate"]
    interpreter = ScriptedInterpreter([bad, good])
    draft, terminal = prepare_draft(
        _request(interpreter="model", utterance="arrivals?"),
        sources, pinned, REPO_ROOT / "evals/ontology-read-analysis",
        interpreter_instance=interpreter,
        live=True,
    )
    assert draft is None
    assert terminal["status"] == "semantic_gap"
    assert interpreter.call_count == 1  # the question must not be "repaired away"


def test_persistent_bad_draft_is_rejected(world):
    pinned, sources = world
    bad = {
        "schemaVersion": 1,
        "requestedFacts": [],
        "constraints": [
            {"name": "rfcName", "semanticType": "sapnexus:Plant",
             "value": "BAPI_X", "source": "explicitUser"}
        ],
        "analysisNodes": [],
        "requestedConclusions": [],
        "assumptions": [],
    }
    interpreter = ScriptedInterpreter([bad, bad])
    draft, terminal = prepare_draft(
        _request(interpreter="model", utterance="x"),
        sources, pinned, REPO_ROOT / "evals/ontology-read-analysis",
        interpreter_instance=interpreter,
        live=True,
    )
    assert draft is None
    assert terminal["status"] == "rejected"
    assert interpreter.call_count == 2
