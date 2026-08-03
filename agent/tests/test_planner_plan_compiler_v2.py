from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
from sap_nexus_agent.planner.plan_compiler import Gap, Flag
from sap_nexus_agent.planner.plan_compiler_v2 import PlanCompileResult, compile_plan_v2
from sap_nexus_agent.semantic_planning import (
    build_registry_snapshot,
    load_semantic_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_plan_compile_result_is_frozen_and_carries_v2_fields():
    gap = Gap(kind="missing_parameter", detail="material")
    flag = Flag(kind="invalid_plan_graph", detail="x")
    result = PlanCompileResult(
        plan_graph={"planGraphVersion": 2, "nodes": []},
        gaps=[gap],
        governance_flags=[flag],
        projection_ref=[],
        rule_set_refs=[],
        snapshot_id="sha256:" + "0" * 64,
        rationale="v2 dry-run",
    )
    assert dataclasses.is_dataclass(result)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.rationale = "mutated"  # type: ignore[misc]
    assert result.projection_ref == []
    assert result.rule_set_refs == []
    assert result.snapshot_id.startswith("sha256:")


def _real_sources():
    return load_semantic_sources(REPO_ROOT)


def _real_snapshot():
    return build_registry_snapshot(_real_sources())


def _dual_read_handoff(snapshot) -> EscalationHandoff:
    return EscalationHandoff(
        reason="dual-read",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA4B", "plant": "5300"},
                missing=[],
            ),
            MatchedIntent(
                capability_id="MM.PurchaseOrder.GetList",
                parameters={"material": "DEMOA4B", "plant": "5300"},
                missing=[],
            ),
        ],
        utterance="show inventory and PO for material DEMOA4B at plant 5300",
        registry_snapshot_id=snapshot.snapshot_id,
    )


def test_compile_plan_v2_produces_dual_read_plan_with_goal_constraint_sources():
    snapshot = _real_snapshot()
    sources = _real_sources()
    result = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)
    assert result.plan_graph["planGraphVersion"] == 2
    assert result.snapshot_id == snapshot.snapshot_id
    cap_ids = {n["capabilityId"] for n in result.plan_graph["nodes"]}
    assert cap_ids == {"MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"}
    # 双 READ -> readPartition 含两节点，actionPartition 空
    assert set(result.plan_graph["readPartition"]) == {
        n["nodeId"] for n in result.plan_graph["nodes"]
    }
    assert result.plan_graph["actionPartition"] == []
    # 参数源为 goalConstraint
    for node in result.plan_graph["nodes"]:
        kinds = {b["source"]["kind"] for b in node["parameterBindings"]}
        assert kinds == {"goalConstraint"}
    # refs 空
    assert result.plan_graph["projectionRef"] == []
    assert result.plan_graph["ruleSetRefs"] == []
    # 无 Gateway 调用、无 invalid flag
    assert not any(
        f.kind == "invalid_plan_graph" for f in result.governance_flags
    )


def test_compile_plan_v2_is_deterministic():
    snapshot = _real_snapshot()
    sources = _real_sources()
    first = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)
    second = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)
    assert first == second
    assert first.plan_graph == second.plan_graph
