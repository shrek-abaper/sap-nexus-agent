from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
    build_registry_snapshot,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.graph import SemanticGraphCompiler
from sap_nexus_agent.semantic_planning.validation_v2 import validate_plan_graph_v2

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _resolve_ref(branch: dict, root: dict) -> dict:
    """Resolve a local ``$ref`` (e.g. ``#/$defs/foo``) to its target ``$def``.

    Inline branches (no ``$ref``) are returned as-is.  The v1 schema uses
    ``$ref`` branches in ``parameterSource.oneOf`` while the v2 schema uses
    inline branches; this helper normalises both so the same assertion logic
    can introspect ``properties.kind.const`` on every branch.
    """
    ref = branch.get("$ref")
    if not ref:
        return branch
    target = root
    for part in ref.lstrip("#/").split("/"):
        target = target[part]
    return target


def test_plan_graph_v2_schema_carries_partition_and_registered_default():
    schema = _load_schema("plan-graph-v2.schema.json")
    assert schema["properties"]["planGraphVersion"]["const"] == 2
    required = schema["required"]
    for field in (
        "readPartition",
        "actionPartition",
        "projectionRef",
        "ruleSetRefs",
    ):
        assert field in required, f"v2 schema must require {field}"
    source_kinds = {
        branch["properties"]["kind"]["const"]
        for branch in schema["$defs"]["parameterSource"]["oneOf"]
    }
    assert source_kinds == {
        "goalConstraint",
        "literal",
        "factField",
        "registeredDefault",
    }
    # readPartition / actionPartition: unique string arrays
    for part in ("readPartition", "actionPartition"):
        assert schema["properties"][part]["type"] == "array"
        assert schema["properties"][part]["uniqueItems"] is True


def test_plan_graph_v1_schema_remains_unchanged():
    """Design Doc §4.1 / spec R1: v1 schema (planGraphVersion:1) 未改动。"""
    v1 = _load_schema("plan-graph.schema.json")
    assert v1["properties"]["planGraphVersion"]["const"] == 1
    # v1 不含 v2 字段
    for field in ("readPartition", "actionPartition", "projectionRef", "ruleSetRefs"):
        assert field not in v1["properties"]
        assert field not in v1["required"]
    # v1 参数源仍是 3 源闭集
    v1_kinds = {
        _resolve_ref(branch, v1)["properties"]["kind"]["const"]
        for branch in v1["$defs"]["parameterSource"]["oneOf"]
    }
    assert v1_kinds == {"goalConstraint", "literal", "factField"}


def _load_fixture(name: str) -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "agent/tests/fixtures/semantic_planning" / name).read_text(
            encoding="utf-8"
        )
    )


def test_v1_fixture_passes_v1_schema_and_fails_v2_schema():
    fixture = _load_fixture("plan-material-supply.yaml")
    v1 = _load_schema("plan-graph.schema.json")
    v2 = _load_schema("plan-graph-v2.schema.json")
    jsonschema.Draft202012Validator(v1).validate(fixture)  # 不抛
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(v2).validate(fixture)


def _real_sources() -> SemanticSourceDocuments:
    return load_semantic_sources(REPO_ROOT)


def _real_snapshot() -> RegistrySnapshot:
    return build_registry_snapshot(_real_sources())


def _valid_v2_plan(snapshot: RegistrySnapshot) -> dict:
    """手工构造一个合法 v2 plan（inventory 单节点，READ_ONLY）。"""
    return {
        "planGraphVersion": 2,
        "planId": "plan.v2.test",
        "goalId": "goal.v2.test",
        "executionMode": "READ_ONLY",
        "snapshotId": snapshot.snapshot_id,
        "nodes": [
            {
                "nodeId": "node.MM.Inventory.GetAvailability",
                "capabilityId": "MM.Inventory.GetAvailability",
                "parameterBindings": [
                    {
                        "parameterName": "material",
                        "source": {
                            "kind": "goalConstraint",
                            "constraintName": "material",
                        },
                    },
                    {
                        "parameterName": "plant",
                        "source": {
                            "kind": "goalConstraint",
                            "constraintName": "plant",
                        },
                    },
                ],
                "producesFactTypes": ["sapnexus:InventoryAvailabilityFact"],
                "governance": {
                    "capabilityKind": "Function",
                    "sideEffect": "none",
                    "requiresApproval": False,
                    "approvalPolicy": "not_required",
                },
            }
        ],
        "edges": [],
        "topologicalOrder": ["node.MM.Inventory.GetAvailability"],
        "goalOutputs": [
            {
                "factTypeId": "sapnexus:InventoryAvailabilityFact",
                "producerNodeId": "node.MM.Inventory.GetAvailability",
            }
        ],
        "readPartition": ["node.MM.Inventory.GetAvailability"],
        "actionPartition": [],
        "projectionRef": [],
        "ruleSetRefs": [],
    }


def _goal_spec_for_inventory() -> dict:
    return {
        "goalSpecVersion": 1,
        "goalId": "goal.v2.test",
        "goalType": "sapnexus:GoalFor:InventoryAvailabilityFact",
        "executionMode": "READ_ONLY",
        "desiredFactTypes": ["sapnexus:InventoryAvailabilityFact"],
        "constraints": [
            {"name": "material", "semanticType": "sapnexus:MaterialNumber", "value": "M1"},
            {"name": "plant", "semanticType": "sapnexus:Plant", "value": "5300"},
        ],
    }


def test_validate_plan_graph_v2_accepts_valid_v2_plan():
    snapshot = _real_snapshot()
    sources = _real_sources()
    graph = SemanticGraphCompiler().compile(sources)
    plan = _valid_v2_plan(snapshot)
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is True, report.issues


def test_validate_plan_graph_v2_rejects_action_in_read_partition():
    snapshot = _real_snapshot()
    sources = _real_sources()
    graph = SemanticGraphCompiler().compile(sources)
    plan = _valid_v2_plan(snapshot)
    # 把 inventory 节点的 governance 改成 Action 并放入 readPartition
    plan["nodes"][0]["governance"] = {
        "capabilityKind": "Action",
        "sideEffect": "sap_write",
        "requiresApproval": True,
        "approvalPolicy": "human_required",
    }
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    codes = {issue.code for issue in report.issues}
    assert "PARTITION_GOVERNANCE_VIOLATION" in codes or "GOVERNANCE_VIOLATION" in codes


def test_validate_plan_graph_v2_empty_refs_pass():
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["projectionRef"] = []
    plan["ruleSetRefs"] = []
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is True, report.issues


def test_validate_plan_graph_v2_unknown_projection_ref_fails_closed():
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["projectionRef"] = ["sapnexus:Projection:DoesNotExist"]
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    codes = {issue.code for issue in report.issues}
    assert "UNKNOWN_PROJECTION_REF" in codes


# ---- Task 13: 7 类 bad-case fail-closed (validator layer) ----


def test_bad_case_unknown_capability_validator():
    """spec R4: unknown capability -> UNKNOWN_CAPABILITY."""
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["nodes"][0]["capabilityId"] = "MM.DoesNotExist.Get"
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "UNKNOWN_CAPABILITY" for i in report.issues)


def test_bad_case_cycle_validator():
    """spec R4: dependency cycle -> DEPENDENCY_CYCLE."""
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    # 加第二个节点 + 互相 dependency edge 形成环
    plan["nodes"].append({
        "nodeId": "node.MM.PurchaseOrder.GetList",
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameterBindings": [],
        "producesFactTypes": ["sapnexus:PurchaseOrderSupplyFact"],
        "governance": plan["nodes"][0]["governance"],
    })
    plan["edges"] = [
        {"edgeId": "e1", "kind": "dependency", "fromNodeId": "node.MM.Inventory.GetAvailability", "toNodeId": "node.MM.PurchaseOrder.GetList"},
        {"edgeId": "e2", "kind": "dependency", "fromNodeId": "node.MM.PurchaseOrder.GetList", "toNodeId": "node.MM.Inventory.GetAvailability"},
    ]
    plan["topologicalOrder"] = ["node.MM.Inventory.GetAvailability", "node.MM.PurchaseOrder.GetList"]
    plan["readPartition"] = ["node.MM.Inventory.GetAvailability", "node.MM.PurchaseOrder.GetList"]
    plan["actionPartition"] = []
    plan["goalOutputs"] = [{"factTypeId": "sapnexus:InventoryAvailabilityFact", "producerNodeId": "node.MM.Inventory.GetAvailability"}]
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "DEPENDENCY_CYCLE" for i in report.issues)


def test_bad_case_type_mismatch_validator():
    """factField source on an identifier parameter -> FACT_TYPE_MISMATCH.

    The inventory capability's ``material`` input has ``bindingKind: identifier``
    (not ``fact``). Replacing the existing ``goalConstraint`` binding for
    ``material`` with a ``factField`` source triggers ``FACT_TYPE_MISMATCH``
    because ``input_field["bindingKind"] != "fact"``.
    """
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    # Replace the "material" binding (goalConstraint) with a factField source.
    # The validator checks: input_field["bindingKind"] != "fact" -> FACT_TYPE_MISMATCH.
    plan["nodes"][0]["parameterBindings"][0] = {
        "parameterName": "material",
        "source": {
            "kind": "factField",
            "producerNodeId": "node.MM.Inventory.GetAvailability",
            "factTypeId": "sapnexus:DoesNotExist",
            "field": "x",
        },
    }
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "FACT_TYPE_MISMATCH" for i in report.issues)


def test_bad_case_inconsistent_relation_validator():
    """dependency edge not matching snapshot dependsOn -> EDGE_INCONSISTENT."""
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["nodes"].append({
        "nodeId": "node.MM.PurchaseOrder.GetList",
        "capabilityId": "MM.PurchaseOrder.GetList",
        "parameterBindings": [],
        "producesFactTypes": ["sapnexus:PurchaseOrderSupplyFact"],
        "governance": plan["nodes"][0]["governance"],
    })
    # snapshot 无 dependsOn 关系，但 plan author 了一条 dependency edge
    plan["edges"] = [{"edgeId": "e1", "kind": "dependency", "fromNodeId": "node.MM.Inventory.GetAvailability", "toNodeId": "node.MM.PurchaseOrder.GetList"}]
    plan["topologicalOrder"] = ["node.MM.Inventory.GetAvailability", "node.MM.PurchaseOrder.GetList"]
    plan["readPartition"] = ["node.MM.Inventory.GetAvailability", "node.MM.PurchaseOrder.GetList"]
    plan["actionPartition"] = []
    plan["goalOutputs"] = [{"factTypeId": "sapnexus:InventoryAvailabilityFact", "producerNodeId": "node.MM.Inventory.GetAvailability"}]
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "EDGE_INCONSISTENT" for i in report.issues)


def test_bad_case_action_in_read_validator():
    """spec R3: Action 节点入 readPartition -> PARTITION_GOVERNANCE_VIOLATION."""
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    plan["nodes"][0]["governance"] = {
        "capabilityKind": "Action", "sideEffect": "sap_write",
        "requiresApproval": True, "approvalPolicy": "human_required",
    }
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(
        i.code == "PARTITION_GOVERNANCE_VIOLATION" or i.code == "GOVERNANCE_VIOLATION"
        for i in report.issues
    )


def test_bad_case_missing_source_validator():
    """spec R4: required parameter no source -> PARAMETER_SOURCE_MISSING."""
    snapshot = _real_snapshot()
    plan = _valid_v2_plan(snapshot)
    # 清空 inventory 节点的 parameterBindings（material/plant 都无源）
    plan["nodes"][0]["parameterBindings"] = []
    graph = SemanticGraphCompiler().compile(_real_sources())
    report = validate_plan_graph_v2(graph, snapshot, _goal_spec_for_inventory(), plan)
    assert report.valid is False
    assert any(i.code == "PARAMETER_SOURCE_MISSING" for i in report.issues)
