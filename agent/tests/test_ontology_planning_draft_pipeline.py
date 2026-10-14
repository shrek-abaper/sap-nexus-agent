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


def test_model_interpreter_requires_live_flag(world, monkeypatch):
    pinned, sources = world
    monkeypatch.delenv("SAP_NEXUS_LLM_LIVE", raising=False)
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


def test_repair_round_recovers_unknown_field(world):
    pinned, sources = world
    good = json.loads(
        (REPO_ROOT / "evals/ontology-read-analysis/drafts/q1-stock-and-unit.json").read_text()
    )
    bad = json.loads(json.dumps(good))
    bad["requestedFacts"][0]["fields"] = ["deliveryDate"]
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
