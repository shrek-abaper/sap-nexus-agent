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
