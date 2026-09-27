"""Tests for append-only decision trace recording."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from sap_nexus_agent.call_plan import create_call_plan
from sap_nexus_agent.decision_traces import (
    DecisionTraceStore,
    build_decision_record,
    record_turn,
)
from sap_nexus_agent.match_decision import MatchDecision
from sap_nexus_agent.orchestrator import AgentOutcome, run_query
from sap_nexus_agent.eval import FakeGatewayClient

REPO_ROOT = Path(__file__).resolve().parents[2]


def _select_outcome() -> AgentOutcome:
    call_plan = create_call_plan(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA1", "plant": "1000"},
    )
    return AgentOutcome(
        status="success",
        call_plan=call_plan,
        match_decision=MatchDecision(
            "SELECT",
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA1", "plant": "1000"},
        ),
        gateway_trace_id="trace-1",
    )


def test_build_select_record():
    record = build_decision_record("DEMOA1 在 1000 还有多少可用库存", _select_outcome())

    assert record["schema"] == "sap-nexus.decision-trace.v1"
    assert record["decision"] == "SELECT"
    assert record["capabilityId"] == "MM.Inventory.GetAvailability"
    assert record["parameters"] == {"material": "DEMOA1", "plant": "1000"}
    assert record["gatewayTraceId"] == "trace-1"
    assert record["model"] == "rule"


def test_clarify_and_reject_decisions():
    clarify = AgentOutcome(
        status="clarification",
        missing_parameters=["plant"],
        match_decision=MatchDecision("CLARIFY", missing_parameters=["plant"]),
    )
    reject = AgentOutcome(
        status="failure",
        error_type="RAW_SQL_NOT_ALLOWED",
        match_decision=MatchDecision("REJECT", error_type="RAW_SQL_NOT_ALLOWED"),
    )

    assert build_decision_record("查这个料", clarify)["decision"] == "CLARIFY"
    record = build_decision_record("select * from mara", reject)
    assert record["decision"] == "REJECT"
    assert record["errorType"] == "RAW_SQL_NOT_ALLOWED"


def test_utterance_never_stored_but_hash_present():
    utterance = "DEMOA1 的秘密查询包含敏感词"
    record = build_decision_record(utterance, _select_outcome())
    serialized = json.dumps(record, ensure_ascii=False)

    assert "秘密查询包含敏感词" not in serialized
    assert record["utteranceHash"] == hashlib.sha256(utterance.encode("utf-8")).hexdigest()


def test_forbidden_parameter_keys_filtered():
    call_plan = create_call_plan(
        "MM.Inventory.GetAvailability", {"material": "DEMOA1", "token": "SECRET", "plant": "1000"}
    )
    outcome = AgentOutcome(
        status="success",
        call_plan=call_plan,
        match_decision=MatchDecision("SELECT", parameters=dict(call_plan.parameters)),
    )

    record = build_decision_record("查询", outcome)

    assert "token" not in record["parameters"]
    assert record["parameters"] == {"material": "DEMOA1", "plant": "1000"}


def test_store_appends_jsonl(tmp_path):
    path = tmp_path / "nested/decisions.jsonl"
    store = DecisionTraceStore(path)
    store.append(build_decision_record("u1", _select_outcome(), trace_id="t1", now=lambda: "2026-09-27T00:00:00+00:00"))
    store.append(build_decision_record("u2", _select_outcome(), trace_id="t2", now=lambda: "2026-09-27T00:00:01+00:00"))

    lines = path.read_text("utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["traceId"] == "t1"
    assert first["recordedAt"] == "2026-09-27T00:00:00+00:00"


def test_model_label_for_llm_adapter():
    def llm_adapter(*_args, **_kwargs):
        raise NotImplementedError

    record = build_decision_record("u", _select_outcome(), intent_adapter=llm_adapter)

    assert record["model"] == "llm"


def test_user_correction_heuristic():
    call_plan = create_call_plan(
        "MM.Inventory.GetAvailability", {"material": "DEMOA1", "plant": "1000"}
    )
    outcome = AgentOutcome(
        status="success",
        call_plan=call_plan,
        match_decision=MatchDecision("SELECT", capability_id="MM.Inventory.GetAvailability"),
        read_state=SimpleNamespace(
            active_frame=SimpleNamespace(capability_id="MM.PurchaseOrder.GetList"),
            slots={},
        ),
    )

    record = build_decision_record("库存查询", outcome)

    assert record["userCorrection"] is True


def test_record_turn_best_effort_on_unwritable(monkeypatch):
    monkeypatch.setenv("SAP_NEXUS_DECISION_TRACE", "/proc/definitely/not/writable/decisions.jsonl")

    # Must not raise despite the impossible path.
    record_turn("u", _select_outcome())


def test_record_turn_disabled(monkeypatch, tmp_path):
    target = tmp_path / "decisions.jsonl"
    monkeypatch.setenv("SAP_NEXUS_DECISION_TRACE", "off")

    record_turn("u", _select_outcome())

    assert not target.exists()


def test_run_query_records_via_wrapper(monkeypatch, tmp_path):
    trace_path = tmp_path / "decisions.jsonl"
    monkeypatch.setenv("SAP_NEXUS_DECISION_TRACE", str(trace_path))
    case = {
        "id": "wrapper-select",
        "userQuery": "DEMOA1 在 1000 还有多少可用库存？",
        "expected": {"capabilityId": "MM.Inventory.GetAvailability"},
    }

    outcome = run_query(case["userQuery"], FakeGatewayClient(case))

    assert outcome.status == "success"
    lines = trace_path.read_text("utf-8").strip().splitlines()
    record = json.loads(lines[0])
    assert record["decision"] == "SELECT"
    assert record["capabilityId"] == "MM.Inventory.GetAvailability"
