from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

import pytest

from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
from sap_nexus_agent.planner.plan_compiler import Gap, Flag
from sap_nexus_agent.planner.plan_compiler_v2 import PlanCompileResult, compile_plan_v2
from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
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


def test_compile_plan_v2_authors_literal_source_for_identifier_without_constraint():
    snapshot = _real_snapshot()
    sources = _real_sources()
    # handoff 提供 plant 值，但不构造对应 GoalConstraint（移除 plant constraint）
    handoff = EscalationHandoff(
        reason="literal",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "M1", "plant": "5300"},
                missing=[],
            )
        ],
        utterance="inventory for M1 at 5300",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    inv_nodes = [
        n for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "MM.Inventory.GetAvailability"
    ]
    assert inv_nodes
    kinds = {b["source"]["kind"] for b in inv_nodes[0]["parameterBindings"]}
    # material 有 GoalConstraint -> goalConstraint；plant 无 constraint 但有值 -> literal
    assert "literal" in kinds
    literal_bindings = [
        b for b in inv_nodes[0]["parameterBindings"]
        if b["source"]["kind"] == "literal"
    ]
    assert any(b["parameterName"] == "plant" for b in literal_bindings)


# ---- Task 8: factField source + data edge authoring ----


def _unfreeze(value):
    """Recursively convert frozen MappingProxyType/tuples to mutable dict/list.

    ``SemanticSourceDocuments.__post_init__`` deep-freezes all fields via
    ``MappingProxyType`` and ``tuple``. ``copy.deepcopy`` cannot pickle
    ``mappingproxy``, so a recursive unfreeze is needed to obtain mutable
    copies for fixture construction.
    """
    if isinstance(value, Mapping):
        return {k: _unfreeze(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_unfreeze(item) for item in value]
    return value


def _sources_with_fact_field() -> tuple[SemanticSourceDocuments, RegistrySnapshot]:
    """Construct a custom sources with a fact input: producer outputs
    ``sapnexus:InventoryAvailabilityFact``, consumer consumes a field of it."""
    base = _real_sources()
    caps = _unfreeze(base.capabilities)
    facts = _unfreeze(base.fact_types)
    # Append a consumer capability whose input bindingKind=fact
    caps["capabilities"].append({
        "capabilityId": "Test.Consumer.GetSummary",
        "name": "Test Consumer",
        "description": "Consumes a fact field",
        "domain": "MM",
        "businessObject": "Test",
        "ontologyIri": "sapnexus:Test_Consumer",
        "semanticType": "sapnexus:TestConsumerReadFunction",
        "aliases": [],
        "status": "active",
        "kind": "Function",
        "inputs": [
            {
                "name": "inventoryFact",
                "semanticType": "sapnexus:InventoryAvailabilityFact",
                "required": True,
                "bindingKind": "fact",
                "satisfiableByFactType": "sapnexus:InventoryAvailabilityFact",
            }
        ],
        "outputs": [
            {"name": "summary", "factTypeRef": "sapnexus:TestSummaryFact"}
        ],
        "governance": {
            "sideEffect": "none",
            "requiresApproval": False,
            "approvalPolicy": "not_required",
            "dataClassification": "internal",
        },
        "executor": {"type": "ODATA"},
        "executorBinding": {"type": "ODATA", "bindingId": "test-binding"},
    })
    if "sapnexus:TestSummaryFact" not in facts.get("factTypes", []):
        facts["factTypes"].append({"factTypeId": "sapnexus:TestSummaryFact", "fields": []})
    sources = SemanticSourceDocuments(
        capabilities=caps,
        executor_bindings=base.executor_bindings,
        fact_types=facts,
        relations=base.relations,
    )
    snapshot = build_registry_snapshot(sources)
    return sources, snapshot


def test_compile_plan_v2_authors_fact_field_source_and_data_edge():
    sources, snapshot = _sources_with_fact_field()
    handoff = EscalationHandoff(
        reason="fact-field",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "M1", "plant": "5300"},
                missing=[],
            ),
            MatchedIntent(
                capability_id="Test.Consumer.GetSummary",
                parameters={},
                missing=[],
            ),
        ],
        utterance="summary from inventory",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    consumer_nodes = [
        n for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "Test.Consumer.GetSummary"
    ]
    assert consumer_nodes
    fact_bindings = [
        b for b in consumer_nodes[0]["parameterBindings"]
        if b["source"]["kind"] == "factField"
    ]
    assert fact_bindings, "expected a factField source binding"
    # matching data edge
    data_edges = [e for e in result.plan_graph["edges"] if e["kind"] == "data"]
    assert len(data_edges) == 1
    edge = data_edges[0]
    assert edge["factTypeId"] == "sapnexus:InventoryAvailabilityFact"
    assert edge["toNodeId"] == consumer_nodes[0]["nodeId"]
    inv_nodes = [
        n for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "MM.Inventory.GetAvailability"
    ]
    assert edge["fromNodeId"] == inv_nodes[0]["nodeId"]
    # v2 validator must accept the factField source + data edge
    assert not any(
        f.kind == "invalid_plan_graph" for f in result.governance_flags
    )
