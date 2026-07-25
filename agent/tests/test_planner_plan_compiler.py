"""Unit tests for ``planner.plan_compiler`` (S2-B, Plan Task 8).

Covers the deterministic ``PlanCompiler`` dry-run:

- ``Gap`` / ``Flag`` / ``DryRunResult`` frozen dataclasses.
- ``compile_dry_run(goal, snapshot, sources) -> DryRunResult`` builds a
  ``PlanGraph`` v1 dict from ``GoalSpec`` + ``CapabilityCard`` projection
  and validates it through the S1 ``semantic_planning.validation.\
  validate_plan_graph`` entry (no reimplementation).
- Deterministic: no LLM, no Gateway/SAP. The Gateway mock must record
  zero ``validate`` / ``execute`` calls.
- Gaps: ``missing_capability`` (desired Fact Type has no producer) and
  ``missing_parameter`` (required input has no source) are recorded as
  advisory signals whether or not the S1 validator passes.
- Governance flags: ``write_side_effect`` / ``approval_required`` for
  valid plans; ``invalid_plan_graph`` (single flag) when the S1
  validator fails. No exception is raised on invalid input.
- Determinism: identical inputs produce identical ``DryRunResult``.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
sections "PlanCompiler", "dry-run 输出", "错误处理与边界条件".
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sap_nexus_agent.gateway_client import GatewayClientProtocol
from sap_nexus_agent.planner import GoalConstraint, GoalSpec
from sap_nexus_agent.planner.plan_compiler import (
    DryRunResult,
    Flag,
    Gap,
    compile_dry_run,
)
from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
    build_registry_snapshot,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.graph import SemanticGraphCompiler
from sap_nexus_agent.semantic_planning.validation import validate_plan_graph

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---- fixtures / helpers ----


def _real_sources() -> SemanticSourceDocuments:
    return load_semantic_sources(REPO_ROOT)


def _real_snapshot() -> RegistrySnapshot:
    return build_registry_snapshot(_real_sources())


def _goal(
    desired: tuple[str, ...] = (
        "sapnexus:InventoryAvailabilityFact",
        "sapnexus:PurchaseOrderSupplyFact",
    ),
    constraints: tuple[GoalConstraint, ...] = (
        GoalConstraint("material", "sapnexus:MaterialNumber", "DEMOA4B"),
        GoalConstraint("plant", "sapnexus:Plant", "5300"),
    ),
    goal_id: str = "goal.dry-run.fixture",
    execution_mode: str = "PLAN_ONLY",
) -> GoalSpec:
    return GoalSpec(
        goal_id=goal_id,
        goal_type="sapnexus:PlannerDryRunGoal",
        desired_fact_types=desired,
        execution_mode=execution_mode,
        constraints=constraints,
    )


def _goal_pr_create_all_params() -> GoalSpec:
    """Goal referencing the PR create Fact Type with all 6 required params.

    ``MM.PR.CreateDraft`` is a write capability (``sideEffect=sap_write``,
    ``requiresApproval=true``). With every required identifier input bound
    via a goal constraint the S1 PlanGraph validator passes (PLAN_ONLY
    allows write capabilities), so governance flags surface
    ``write_side_effect`` / ``approval_required`` rather than
    ``invalid_plan_graph``.
    """
    return GoalSpec(
        goal_id="goal.pr-create-dry-run",
        goal_type="sapnexus:GoalFor:PurchaseRequisitionCreatedFact",
        desired_fact_types=("sapnexus:PurchaseRequisitionCreatedFact",),
        execution_mode="PLAN_ONLY",
        constraints=(
            GoalConstraint("material", "sapnexus:MaterialNumber", "M1"),
            GoalConstraint("plant", "sapnexus:Plant", "5100"),
            GoalConstraint("quantity", "sapnexus:Quantity", 10),
            GoalConstraint("unit", "sapnexus:UnitOfMeasure", "EA"),
            GoalConstraint("delivery_date", "sapnexus:DeliveryDate", "2026-08-01"),
            GoalConstraint("purchasing_group", "sapnexus:PurchasingGroup", "PG1"),
        ),
    )


# ---- dataclass shape ----


def test_gap_flag_and_dry_run_result_are_frozen_dataclasses():
    """Design Doc §dry-run 输出: ``Gap`` / ``Flag`` / ``DryRunResult``
    are immutable value objects."""
    gap = Gap(kind="missing_parameter", detail="material")
    flag = Flag(kind="write_side_effect", detail="MM.PR.CreateDraft")
    result = DryRunResult(
        plan_graph={"nodes": []},
        gaps=[gap],
        governance_flags=[flag],
        rationale="x",
    )
    for obj in (gap, flag, result):
        assert dataclasses.is_dataclass(obj)
        with pytest.raises(dataclasses.FrozenInstanceError):
            obj.kind = "mutated"  # type: ignore[misc]
    # DryRunResult has no ``kind`` attr; mutate a real field instead.
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.rationale = "mutated"  # type: ignore[misc]


# ---- basic shape ----


def test_compile_dry_run_returns_dry_run_result_with_plan_graph_shape():
    result = compile_dry_run(_goal(), _real_snapshot(), _real_sources())
    assert isinstance(result, DryRunResult)
    assert isinstance(result.plan_graph, dict)
    # S1 PlanGraph v1 required top-level fields.
    for key in (
        "planGraphVersion",
        "planId",
        "goalId",
        "executionMode",
        "snapshotId",
        "nodes",
        "edges",
        "topologicalOrder",
        "goalOutputs",
    ):
        assert key in result.plan_graph, f"plan_graph missing {key}"
    assert isinstance(result.gaps, list)
    assert isinstance(result.governance_flags, list)
    assert isinstance(result.rationale, str) and result.rationale


# ---- S1 validator reuse (valid case) ----


def test_compile_dry_run_builds_plan_graph_that_passes_s1_validator():
    """Design Doc §PlanCompiler: PlanGraph is validated by the S1
    ``validate_plan_graph`` entry (imported, not reimplemented)."""
    goal = _goal()
    snapshot = _real_snapshot()
    sources = _real_sources()
    result = compile_dry_run(goal, snapshot, sources)

    # Re-run the S1 validator against the emitted plan_graph to prove the
    # PlanCompiler did not hand-craft a graph that only it can accept.
    graph = SemanticGraphCompiler().compile(sources)
    report = validate_plan_graph(graph, snapshot, goal.to_dict(), result.plan_graph)
    assert report.valid is True, report.issues
    # Valid plan -> no invalid_plan_graph flag.
    assert not any(f.kind == "invalid_plan_graph" for f in result.governance_flags)
    # Snapshot / goal identity propagated into the plan graph.
    assert result.plan_graph["snapshotId"] == snapshot.snapshot_id
    assert result.plan_graph["goalId"] == goal.goal_id
    assert result.plan_graph["executionMode"] == goal.execution_mode


# ---- gaps: missing_capability ----


def test_compile_dry_run_records_missing_capability_gap_for_unknown_fact_type():
    """Design Doc §错误处理: desired Fact Type with no producer capability
    is recorded as a ``missing_capability`` gap; dry-run does not raise."""
    goal = _goal(
        desired=(
            "sapnexus:InventoryAvailabilityFact",
            "sapnexus:UnknownFactType",
        ),
    )
    result = compile_dry_run(goal, _real_snapshot(), _real_sources())
    missing_capability = [g for g in result.gaps if g.kind == "missing_capability"]
    assert missing_capability, "expected a missing_capability gap"
    assert any("sapnexus:UnknownFactType" in g.detail for g in missing_capability)


# ---- gaps: missing_parameter ----


def test_compile_dry_run_records_missing_parameter_gap_when_required_input_unbound():
    """Design Doc §错误处理: a required parameter with no source is
    recorded as a ``missing_parameter`` gap; dry-run does not raise."""
    goal = _goal(
        desired=("sapnexus:InventoryAvailabilityFact",),
        # Only ``plant`` constraint -> ``material`` required input unbound.
        constraints=(GoalConstraint("plant", "sapnexus:Plant", "5300"),),
    )
    result = compile_dry_run(goal, _real_snapshot(), _real_sources())
    missing_parameter = [g for g in result.gaps if g.kind == "missing_parameter"]
    assert missing_parameter, "expected a missing_parameter gap"
    assert any("material" in g.detail for g in missing_parameter)


# ---- governance flags: write_side_effect + approval_required ----


def test_compile_dry_run_flags_write_side_effect_and_approval_for_write_capability():
    """Design Doc §dry-run 输出: write capability nodes surface
    ``write_side_effect`` and ``approval_required`` governance flags.

    ``MM.PR.CreateDraft`` is ``sideEffect=sap_write`` +
    ``requiresApproval=true``. With all required identifier inputs bound
    the S1 validator passes (PLAN_ONLY permits write capabilities), so
    the governance flags are the advisory ones (not invalid_plan_graph).
    """
    goal = _goal_pr_create_all_params()
    result = compile_dry_run(goal, _real_snapshot(), _real_sources())

    # Valid plan -> S1 validator must have passed.
    assert not any(f.kind == "invalid_plan_graph" for f in result.governance_flags), (
        "write capability with all params bound should produce a valid PlanGraph"
    )
    kinds = {f.kind for f in result.governance_flags}
    assert "write_side_effect" in kinds
    assert "approval_required" in kinds
    assert any("MM.PR.CreateDraft" in f.detail for f in result.governance_flags)


# ---- no Gateway calls (deterministic) ----


def test_compile_dry_run_does_not_call_gateway_validate_or_execute(monkeypatch):
    """Design Doc §PlanCompiler: deterministic dry-run; MUST NOT call
    Gateway ``validate`` / ``execute``.

    Strengthened: patch ``GatewayClient`` to explode if instantiated, so
    an accidental future import is caught at test time rather than in
    production.
    """
    import sap_nexus_agent.gateway_client as gateway_module

    exploding_gateway_class = MagicMock(
        side_effect=AssertionError(
            "GatewayClient must not be instantiated by PlanCompiler"
        )
    )
    monkeypatch.setattr(gateway_module, "GatewayClient", exploding_gateway_class)

    mock_gateway = MagicMock(spec=GatewayClientProtocol)

    result = compile_dry_run(_goal(), _real_snapshot(), _real_sources())

    mock_gateway.validate.assert_not_called()
    mock_gateway.execute.assert_not_called()
    exploding_gateway_class.assert_not_called()
    assert result.plan_graph is not None


# ---- invalid goal -> invalid_plan_graph flag, no exception ----


def test_compile_dry_run_invalid_goal_sets_invalid_plan_graph_flag_without_raising():
    """Design Doc §错误处理: S1 validator failure -> governance_flags
    contains ``invalid_plan_graph``; no exception is raised."""
    # Empty desiredFactTypes -> GoalSpec schema-invalid; PlanGraph built
    # from it cannot satisfy minItems=1 on nodes/goalOutputs/topologicalOrder.
    goal = GoalSpec(
        goal_id="goal.empty",
        goal_type="sapnexus:EmptyGoal",
        desired_fact_types=(),
        execution_mode="PLAN_ONLY",
        constraints=(),
    )
    result = compile_dry_run(goal, _real_snapshot(), _real_sources())
    invalid_flags = [f for f in result.governance_flags if f.kind == "invalid_plan_graph"]
    assert invalid_flags, "expected invalid_plan_graph flag for invalid GoalSpec"
    assert isinstance(result.rationale, str) and result.rationale


# ---- determinism ----


def test_compile_dry_run_is_deterministic_for_identical_inputs():
    goal = _goal()
    snapshot = _real_snapshot()
    sources = _real_sources()
    first = compile_dry_run(goal, snapshot, sources)
    second = compile_dry_run(goal, snapshot, sources)
    assert first == second
    assert first.plan_graph == second.plan_graph


# ---- rationale summarises the dry-run ----


def test_compile_dry_run_rationale_summarises_nodes_gaps_and_flags():
    goal = _goal()
    result = compile_dry_run(goal, _real_snapshot(), _real_sources())
    n_nodes = len(result.plan_graph["nodes"])
    n_gaps = len(result.gaps)
    n_flags = len(result.governance_flags)
    # Rationale must mention each count so the Workbench can surface a
    # human-readable summary without re-deriving it.
    assert str(n_nodes) in result.rationale
    assert str(n_gaps) in result.rationale
    assert str(n_flags) in result.rationale


# ---- parameter source provenance ----


def test_compile_dry_run_uses_goal_constraint_source_kind_for_bound_identifiers():
    """Design Doc §PlanCompiler: parameter sources use the S1 v1
    ``goalConstraint`` / ``literal`` / ``factField`` taxonomy. Bound
    identifier inputs must be projected as ``goalConstraint`` sources."""
    goal = _goal(desired=("sapnexus:InventoryAvailabilityFact",))
    result = compile_dry_run(goal, _real_snapshot(), _real_sources())
    # Find the inventory node and confirm both bound parameters use the
    # goalConstraint source kind.
    inv_nodes = [
        n
        for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "MM.Inventory.GetAvailability"
    ]
    assert inv_nodes, "expected an inventory producer node"
    bindings = inv_nodes[0]["parameterBindings"]
    source_kinds = {b["source"]["kind"] for b in bindings}
    assert source_kinds == {"goalConstraint"}
    binding_names = {b["parameterName"] for b in bindings}
    assert {"material", "plant"}.issubset(binding_names)
