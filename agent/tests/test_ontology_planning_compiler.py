"""SemanticCompiler tests: READ_ONLY PlanGraph v2 + AnalysisPlan DAG."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from sap_nexus_agent.ontology_planning.contracts import (
    AnalysisNodeDraft,
    ObjectSelector,
    RequestedConclusion,
    RequestedFact,
    SemanticGoalDraft,
    TypedConstraint,
)
from sap_nexus_agent.ontology_planning.compiler import (
    CompilerFailure,
    compile,
    goal_spec_for,
)
from sap_nexus_agent.ontology_planning.release import pin_release
from sap_nexus_agent.ontology_planning.resolver import resolve
from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts
from sap_nexus_agent.semantic_planning.validation_v2 import validate_plan_graph_v2

REPO_ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = {"principalId": "local-user-0001", "dataScope": {"tenantId": "default"}}
SCOPE = {"plant": "1000"}


@pytest.fixture(scope="module")
def world():
    pinned = pin_release(REPO_ROOT)
    sources = load_semantic_sources(REPO_ROOT)
    contracts = build_semantic_contracts(sources)
    return pinned, sources, contracts.snapshot, contracts.graph


def _selectors():
    return (
        ObjectSelector("sapnexus:Material", "material", "DEMOA2"),
        ObjectSelector("sapnexus:Plant", "plant", "1000"),
    )


def _q1_draft():
    return SemanticGoalDraft(
        1,
        (
            RequestedFact(
                "sapnexus:InventoryAvailabilityFact",
                ("availableQuantity",),
                _selectors(),
            ),
            RequestedFact(
                "sapnexus:MaterialInfoFact",
                ("baseUnitOfMeasure",),
                _selectors(),
            ),
        ),
        (),
        (),
        (RequestedConclusion("c1", "stock and unit", "evidence"),),
        (),
    )


def test_q1_compiles_valid_read_only_plan(world):
    pinned, sources, snapshot, graph = world
    draft = _q1_draft()
    resolution = resolve(draft, pinned, sources, snapshot, graph, PRINCIPAL)
    plan = compile(draft, resolution, pinned, sources, snapshot, graph, PRINCIPAL, SCOPE)

    assert plan["schemaVersion"] == 1
    read = plan["readPlan"]
    assert read["executionMode"] == "READ_ONLY"
    assert read["actionPartition"] == []
    assert read["snapshotId"] == snapshot.snapshot_id
    node_caps = {n["capabilityId"] for n in read["nodes"]}
    assert node_caps == {"MM.Inventory.GetAvailability", "MM.Material.GetInfo"}
    assert set(read["readPartition"]) == {n["nodeId"] for n in read["nodes"]}
    # Every required identifier input is bound exactly once.
    for node in read["nodes"]:
        assert node["governance"]["requiresApproval"] is False
        bound = {b["parameterName"] for b in node["parameterBindings"]}
        assert {"material", "plant"} <= bound

    goal_spec = goal_spec_for(plan)
    report = validate_plan_graph_v2(graph, snapshot, goal_spec, read)
    assert report.valid, [str(i) for i in report.issues]

    jsonschema.validate(plan, json.loads(
        (REPO_ROOT / "schemas/read-analysis-plan.schema.json").read_text()
    ))


def test_q2_compiles_group_sum_analysis(world):
    pinned, sources, snapshot, graph = world
    draft = SemanticGoalDraft(
        1,
        (
            RequestedFact(
                "sapnexus:InventoryAvailabilityFact",
                ("availableQuantity",),
                _selectors(),
            ),
            RequestedFact(
                "sapnexus:PurchaseOrderSupplyFact",
                ("orderQuantity", "supplier", "purchaseOrderUnit"),
                _selectors(),
            ),
        ),
        (),
        (
            AnalysisNodeDraft(
                "a1",
                "group_sum",
                ({"kind": "factField",
                  "factTypeId": "sapnexus:PurchaseOrderSupplyFact",
                  "field": "orderQuantity"},),
                {"dimensions": ["supplier"], "unitField": "purchaseOrderUnit"},
                (),
            ),
        ),
        (RequestedConclusion("c1", "stock vs grouped PO", "lineage"),),
        (),
    )
    resolution = resolve(draft, pinned, sources, snapshot, graph, PRINCIPAL)
    plan = compile(draft, resolution, pinned, sources, snapshot, graph, PRINCIPAL, SCOPE)
    node_caps = {n["capabilityId"] for n in plan["readPlan"]["nodes"]}
    assert "MM.PurchaseOrder.GetList" in node_caps
    ana = plan["analysisPlan"]["nodes"]
    assert [n["operatorId"] for n in ana] == ["group_sum"]
    assert ana[0]["operatorVersion"] == pinned.operator_versions["group_sum"]
    assert "a1" in plan["analysisPlan"]["outputs"]


def test_plan_id_deterministic(world):
    pinned, sources, snapshot, graph = world
    draft = _q1_draft()
    resolution = resolve(draft, pinned, sources, snapshot, graph, PRINCIPAL)
    first = compile(draft, resolution, pinned, sources, snapshot, graph, PRINCIPAL, SCOPE)
    second = compile(draft, resolution, pinned, sources, snapshot, graph, PRINCIPAL, SCOPE)
    assert first["planId"] == second["planId"]
    assert first["planId"].startswith("sha256:")


def test_write_capability_rejected(world):
    pinned, sources, snapshot, graph = world
    from sap_nexus_agent.ontology_planning.resolver import DesiredFact
    from types import SimpleNamespace

    resolution = SimpleNamespace(
        status="complete",
        desired=(
            DesiredFact(
                "sapnexus:PurchaseRequisitionCreatedFact",
                ("prNumber",),
                "MM.PR.CreateDraft",
                (),
            ),
        ),
        producers={},
        clarification=(),
        gaps=(),
        candidates={},
        closure=(),
        closure_capabilities=(),
    )
    draft = _q1_draft()
    with pytest.raises(CompilerFailure):
        compile(draft, resolution, pinned, sources, snapshot, graph, PRINCIPAL, SCOPE)


def test_analysis_cycle_and_unknown_field_rejected(world):
    pinned, sources, snapshot, graph = world
    base = _q1_draft()
    cyclic = SemanticGoalDraft(
        1, base.requested_facts, (),
        (
            AnalysisNodeDraft("a1", "select_fields", (), {}, ("a2",)),
            AnalysisNodeDraft("a2", "filter_eq", (), {}, ("a1",)),
        ),
        base.requested_conclusions, (),
    )
    resolution = resolve(cyclic, pinned, sources, snapshot, graph, PRINCIPAL)
    with pytest.raises(CompilerFailure, match="cycle"):
        compile(cyclic, resolution, pinned, sources, snapshot, graph, PRINCIPAL, SCOPE)

    bad_field = SemanticGoalDraft(
        1, base.requested_facts, (),
        (
            AnalysisNodeDraft(
                "a1", "select_fields",
                ({"kind": "factField",
                  "factTypeId": "sapnexus:InventoryAvailabilityFact",
                  "field": "mrpElementLines"},),
                {"fields": []}, (),
            ),
        ),
        base.requested_conclusions, (),
    )
    # mrpElementLines is not allowlisted: resolver gaps first; compile must not
    # succeed for a plan carrying an illegal factField.
    resolution = resolve(bad_field, pinned, sources, snapshot, graph, PRINCIPAL)
    with pytest.raises(CompilerFailure):
        compile(bad_field, resolution, pinned, sources, snapshot, graph, PRINCIPAL, SCOPE)
