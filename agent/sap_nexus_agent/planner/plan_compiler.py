"""Deterministic PlanCompiler dry-run (S2-B, Plan Task 8).

Compiles a ``GoalSpec`` + ``RegistrySnapshot`` + ``SemanticSourceDocuments``
into a ``DryRunResult`` carrying a validated S1 ``PlanGraph`` v1, advisory
gaps, and governance flags. The compiler is deterministic: it does not
call the LLM, the Gateway, or SAP. The S1 ``validate_plan_graph`` entry
is imported and reused - graph validation is not reimplemented here
(Design Doc §风险 "S2-B 复用 S1 validator 契约漂移").

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
sections "PlanCompiler", "dry-run 输出", "错误处理与边界条件".
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sap_nexus_agent.planner.capability_card import CapabilityCard, discover_cards
from sap_nexus_agent.planner.goal_spec import GoalSpec
from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
)
from sap_nexus_agent.semantic_planning.graph import SemanticGraphCompiler
from sap_nexus_agent.semantic_planning.validation import validate_plan_graph

# S1 PlanGraph v1 source-kind taxonomy (per schemas/plan-graph.schema.json).
_SOURCE_KIND_GOAL_CONSTRAINT = "goalConstraint"
_SOURCE_KIND_LITERAL = "literal"
_SOURCE_KIND_FACT_FIELD = "factField"

# Governance flag kinds (Design Doc §dry-run 输出).
_FLAG_INVALID_PLAN_GRAPH = "invalid_plan_graph"
_FLAG_WRITE_SIDE_EFFECT = "write_side_effect"
_FLAG_APPROVAL_REQUIRED = "approval_required"

# Gap kinds (Design Doc §错误处理 "PlanCompiler 缺口").
_GAP_MISSING_CAPABILITY = "missing_capability"
_GAP_MISSING_PARAMETER = "missing_parameter"

# Side effects that count as write side effects for governance flags.
_WRITE_SIDE_EFFECTS = frozenset({"write", "sap_write"})


@dataclass(frozen=True)
class Gap:
    """Advisory gap recorded by the dry-run (no execution authority).

    - ``missing_capability``: a desired Fact Type has no active producer
      capability in the registry.
    - ``missing_parameter``: a producer node's required input has no
      parameter source (goalConstraint / literal / factField).
    """

    kind: str  # "missing_capability" | "missing_parameter"
    detail: str


@dataclass(frozen=True)
class Flag:
    """Governance flag recorded by the dry-run.

    - ``write_side_effect``: the plan contains a write capability node.
    - ``approval_required``: the plan contains a capability that requires
      human approval before execution.
    - ``invalid_plan_graph``: the S1 ``validate_plan_graph`` validator
      rejected the compiled PlanGraph; the dry-run must not be executed.
    """

    kind: str  # "approval_required" | "write_side_effect" | "invalid_plan_graph"
    detail: str


@dataclass(frozen=True)
class DryRunResult:
    """Deterministic dry-run output.

    ``plan_graph`` is the S1 ``PlanGraph`` v1 dict (camelCase JSON shape)
    - it is returned even when the S1 validator fails so the Workbench
    can render the partial graph for debugging. ``gaps`` /
    ``governance_flags`` are advisory lists; ``rationale`` is a short
    human-readable summary.
    """

    plan_graph: dict[str, Any]
    gaps: list[Gap]
    governance_flags: list[Flag]
    rationale: str


def compile_dry_run(
    goal: GoalSpec,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
) -> DryRunResult:
    """Compile a deterministic dry-run plan from a ``GoalSpec``.

    Deterministic: no LLM, no Gateway/SAP. The compiled ``PlanGraph`` is
    validated by the S1 ``validate_plan_graph`` entry (imported, not
    reimplemented). On validator failure the result carries a single
    ``invalid_plan_graph`` flag and no exception is raised.
    """
    cards = discover_cards(snapshot, sources)
    raw_capabilities = _index_raw_capabilities(sources)
    plan_graph = _build_plan_graph(goal, snapshot, cards, raw_capabilities)
    gaps = _compute_gaps(goal, cards, plan_graph)

    graph = SemanticGraphCompiler().compile(sources)
    report = validate_plan_graph(graph, snapshot, goal.to_dict(), plan_graph)

    n_nodes = len(plan_graph["nodes"])
    n_gaps = len(gaps)
    if not report.valid:
        flags = [Flag(_FLAG_INVALID_PLAN_GRAPH, _format_issues(report.issues))]
        rationale = (
            f"S1 validator failed: {len(report.issues)} issue(s); "
            f"dry-run compiled {n_nodes} node(s), {n_gaps} gap(s), 1 flag(s)"
        )
    else:
        flags = _compute_governance_flags(plan_graph, cards)
        n_flags = len(flags)
        rationale = (
            f"dry-run compiled {n_nodes} node(s), "
            f"{n_gaps} gap(s), {n_flags} flag(s)"
        )

    return DryRunResult(
        plan_graph=plan_graph,
        gaps=gaps,
        governance_flags=flags,
        rationale=rationale,
    )


# ---- PlanGraph construction ----


def _build_plan_graph(
    goal: GoalSpec,
    snapshot: RegistrySnapshot,
    cards: list[CapabilityCard],
    raw_capabilities: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a ``PlanGraph`` v1 dict from the goal + capability cards.

    Producer selection: for each desired Fact Type, the first active
    capability (sorted by ``capability_id`` for determinism) whose
    ``produces_fact_types`` contains it is selected. Desired Fact Types
    with no producer are skipped (recorded as ``missing_capability``
    gaps by ``_compute_gaps``).

    Parameter sources: required identifier inputs are bound via
    ``goalConstraint`` when a goal constraint matches by name AND
    semantic type. ``literal`` / ``factField`` sources are not authored
    here - unbound required inputs become ``missing_parameter`` gaps.
    No ``data`` / ``dependency`` edges are authored (the registry has no
    ``dependsOn`` relations and the dry-run does not wire fact fields).
    """
    producers_by_fact = _index_producers_by_fact_type(cards)

    nodes: list[dict[str, Any]] = []
    node_ids: list[str] = []
    node_id_by_capability: dict[str, str] = {}
    fact_type_to_node: dict[str, str] = {}

    for fact_type in goal.desired_fact_types:
        producers = producers_by_fact.get(fact_type)
        if not producers:
            continue
        card = producers[0]
        node_id = node_id_by_capability.get(card.capability_id)
        if node_id is None:
            node_id = _node_id_for(card.capability_id)
            node_id_by_capability[card.capability_id] = node_id
            node_ids.append(node_id)
            raw = raw_capabilities.get(card.capability_id, {})
            nodes.append(_build_node(card, goal, node_id, raw))
        fact_type_to_node[fact_type] = node_id

    goal_outputs = [
        {"factTypeId": fact_type, "producerNodeId": node_id}
        for fact_type, node_id in fact_type_to_node.items()
    ]

    return {
        "planGraphVersion": 1,
        "planId": _plan_id_for(goal),
        "goalId": goal.goal_id,
        "executionMode": goal.execution_mode,
        "snapshotId": snapshot.snapshot_id,
        "nodes": nodes,
        "edges": [],
        "topologicalOrder": list(node_ids),
        "goalOutputs": goal_outputs,
    }


def _build_node(
    card: CapabilityCard,
    goal: GoalSpec,
    node_id: str,
    raw_capability: Mapping[str, Any],
) -> dict[str, Any]:
    constraints_by_name = {c.name: c for c in goal.constraints}
    bindings: list[dict[str, Any]] = []
    for inp in card.inputs:
        if not inp.required:
            continue
        constraint = constraints_by_name.get(inp.name)
        if (
            inp.binding_kind == "identifier"
            and constraint is not None
            and constraint.semantic_type == inp.semantic_type
        ):
            bindings.append(
                {
                    "parameterName": inp.name,
                    "source": {
                        "kind": _SOURCE_KIND_GOAL_CONSTRAINT,
                        "constraintName": constraint.name,
                    },
                }
            )
        # Unbound required inputs are left without a parameterBinding;
        # _compute_gaps records a missing_parameter gap and the S1
        # validator reports PARAMETER_SOURCE_MISSING. ``literal`` and
        # ``factField`` sources are not authored by the dry-run.
    return {
        "nodeId": node_id,
        "capabilityId": card.capability_id,
        "parameterBindings": bindings,
        "producesFactTypes": sorted(card.produces_fact_types),
        "governance": _project_node_governance(raw_capability),
    }


def _project_node_governance(
    raw_capability: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the governance block expected by the S1 validator.

    The S1 validator compares ``node["governance"]`` against the registry
    projection (``capabilityKind`` from ``capability["kind"]`` plus the
    three ``governance`` fields). Reading from the raw capability (not
    the ``CapabilityCard``) keeps the projection exact without extending
    Task 7's ``Governance`` dataclass.
    """
    governance = raw_capability.get("governance") or {}
    return {
        "capabilityKind": raw_capability.get("kind", "Function"),
        "sideEffect": governance.get("sideEffect", "none"),
        "requiresApproval": governance.get("requiresApproval", False),
        "approvalPolicy": governance.get("approvalPolicy", "not_required"),
    }


# ---- gaps ----


def _compute_gaps(
    goal: GoalSpec,
    cards: list[CapabilityCard],
    plan_graph: dict[str, Any],
) -> list[Gap]:
    """Compute advisory gaps (always recorded, independent of validator)."""
    gaps: list[Gap] = []

    producible_fact_types: set[str] = set()
    for card in cards:
        producible_fact_types.update(card.produces_fact_types)
    for fact_type in goal.desired_fact_types:
        if fact_type not in producible_fact_types:
            gaps.append(Gap(kind=_GAP_MISSING_CAPABILITY, detail=fact_type))

    cards_by_id = {c.capability_id: c for c in cards}
    for node in plan_graph["nodes"]:
        card = cards_by_id.get(node["capabilityId"])
        if card is None:
            continue
        bound_names = {
            binding["parameterName"]
            for binding in node["parameterBindings"]
            if isinstance(binding, Mapping)
        }
        for inp in card.inputs:
            if inp.required and inp.name not in bound_names:
                gaps.append(
                    Gap(
                        kind=_GAP_MISSING_PARAMETER,
                        detail=f"{card.capability_id}.{inp.name}",
                    )
                )

    return gaps


# ---- governance flags ----


def _compute_governance_flags(
    plan_graph: dict[str, Any],
    cards: list[CapabilityCard],
) -> list[Flag]:
    """Compute advisory governance flags for a valid PlanGraph."""
    cards_by_id = {c.capability_id: c for c in cards}
    flags: list[Flag] = []
    seen: set[tuple[str, str]] = set()
    for node in plan_graph["nodes"]:
        card = cards_by_id.get(node["capabilityId"])
        if card is None:
            continue
        if card.governance.side_effect in _WRITE_SIDE_EFFECTS:
            key = (_FLAG_WRITE_SIDE_EFFECT, card.capability_id)
            if key not in seen:
                seen.add(key)
                flags.append(
                    Flag(kind=_FLAG_WRITE_SIDE_EFFECT, detail=card.capability_id)
                )
        if card.governance.requires_approval:
            key = (_FLAG_APPROVAL_REQUIRED, card.capability_id)
            if key not in seen:
                seen.add(key)
                flags.append(
                    Flag(kind=_FLAG_APPROVAL_REQUIRED, detail=card.capability_id)
                )
    return flags


# ---- helpers ----


def _index_producers_by_fact_type(
    cards: list[CapabilityCard],
) -> dict[str, list[CapabilityCard]]:
    indexed: dict[str, list[CapabilityCard]] = {}
    for card in cards:
        for fact_type in card.produces_fact_types:
            indexed.setdefault(fact_type, []).append(card)
    for fact_type in indexed:
        indexed[fact_type].sort(key=lambda c: c.capability_id)
    return indexed


def _index_raw_capabilities(
    sources: SemanticSourceDocuments,
) -> dict[str, Mapping[str, Any]]:
    capabilities_yaml = sources.capabilities
    if not isinstance(capabilities_yaml, Mapping):
        return {}
    raw_list = capabilities_yaml.get("capabilities") or []
    if not isinstance(raw_list, (list, tuple)):
        return {}
    indexed: dict[str, Mapping[str, Any]] = {}
    for raw in raw_list:
        if not isinstance(raw, Mapping):
            continue
        cap_id = raw.get("capabilityId")
        if isinstance(cap_id, str) and cap_id:
            indexed[cap_id] = raw
    return indexed


def _node_id_for(capability_id: str) -> str:
    return f"node.{capability_id}"


def _plan_id_for(goal: GoalSpec) -> str:
    return f"plan.dry-run.{goal.goal_id}"


def _format_issues(issues: tuple[Any, ...]) -> str:
    if not issues:
        return "S1 validator reported no issues"
    first = issues[0]
    return f"{first.code} at {first.path}: {first.message}"
