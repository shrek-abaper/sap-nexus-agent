"""PlanGraph v2 deterministic compiler (semantic-plan-authoring-v2).

Compiles EscalationHandoff + RegistrySnapshot + SemanticSourceDocuments
into a PlanCompileResult carrying a validated PlanGraph v2 with full
parameter provenance (4-source closed set), data/dependency edges, and
READ/WRITE partitions. Deterministic: no LLM, no Gateway/SAP.

Design Doc: docs/superpowers/specs/2026-08-03-sap-nexus-semantic-plan-authoring-v2-design.md
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sap_nexus_agent.match_decision import EscalationHandoff
from sap_nexus_agent.planner.capability_card import CapabilityCard, discover_cards
from sap_nexus_agent.planner.goal_spec import GoalConstraint, GoalSpec, build_goal_spec
from sap_nexus_agent.planner.plan_compiler import (
    Flag,
    Gap,
    _SOURCE_KIND_GOAL_CONSTRAINT,
    _compute_gaps,
    _format_issues,
    _index_producers_by_fact_type,
    _index_raw_capabilities,
    _node_id_for,
    _plan_id_for,
    _project_node_governance,
    _FLAG_INVALID_PLAN_GRAPH,
)
from sap_nexus_agent.semantic_planning import (
    RegistrySnapshot,
    SemanticSourceDocuments,
)
from sap_nexus_agent.semantic_planning.graph import SemanticGraphCompiler
from sap_nexus_agent.semantic_planning.validation_v2 import validate_plan_graph_v2

# v2 新增源种类（schema 闭集第 4 种；compiler 本期不产出）。
_SOURCE_KIND_REGISTERED_DEFAULT = "registeredDefault"

# 分区标签（内部使用，不写入 plan_graph）。
_PARTITION_READ = "readPartition"
_PARTITION_ACTION = "actionPartition"


@dataclass(frozen=True)
class PlanCompileResult:
    """v2 dry-run 输出。

    ``plan_graph`` 是 PlanGraph v2 dict（camelCase JSON 形状），校验失败
    时仍返回部分图（不返回 None）。``projection_ref`` / ``rule_set_refs``
    本期空（reserved）。``snapshot_id`` 与 handoff/lease 绑定一致。
    """

    plan_graph: dict[str, Any]
    gaps: list[Gap]
    governance_flags: list[Flag]
    projection_ref: list
    rule_set_refs: list
    snapshot_id: str
    rationale: str


_IDENTIFIER_BINDING_KIND = "identifier"


def _build_goal_v2(
    handoff: EscalationHandoff,
    cards: list[CapabilityCard],
) -> GoalSpec:
    """v2 GoalSpec：constraints 仅限跨能力共享参数。

    与 v1 ``_build_goal_with_constraints``（为所有 identifier 参数建约束）
    不同，v2 仅将出现在 **2+ 个不同能力** 的 matched_intents 中的
    identifier 参数投影为 ``GoalConstraint``。仅出现在单个能力的参数
    由 ``_build_node_v2`` 的 literal 分支绑定（semanticType 从
    InputDescriptor 取，值从 handoff 参数取）。

    设计依据：GoalConstraint 表达的是「目标级」约束（跨能力共享），
    而非单能力参数值。单能力场景下所有 identifier 参数走 literal 源。
    """
    goal = build_goal_spec(handoff, cards)
    cards_by_id = {c.capability_id: c for c in cards}

    # Count distinct capabilities per identifier parameter name.
    param_capabilities: dict[str, set[str]] = {}
    for matched in handoff.matched_intents:
        card = cards_by_id.get(matched.capability_id)
        if card is None:
            continue
        inputs_by_name = {inp.name: inp for inp in card.inputs}
        for param_name in matched.parameters:
            inp = inputs_by_name.get(param_name)
            if inp is None or inp.binding_kind != _IDENTIFIER_BINDING_KIND:
                continue
            param_capabilities.setdefault(param_name, set()).add(
                matched.capability_id
            )

    constraints: list[GoalConstraint] = []
    seen: set[tuple[str, str]] = set()
    for matched in handoff.matched_intents:
        card = cards_by_id.get(matched.capability_id)
        if card is None:
            continue
        inputs_by_name = {inp.name: inp for inp in card.inputs}
        for param_name, param_value in matched.parameters.items():
            inp = inputs_by_name.get(param_name)
            if inp is None or inp.binding_kind != _IDENTIFIER_BINDING_KIND:
                continue
            if len(param_capabilities.get(param_name, set())) < 2:
                continue
            key = (param_name, inp.semantic_type)
            if key in seen:
                continue
            seen.add(key)
            constraints.append(
                GoalConstraint(
                    name=param_name,
                    semantic_type=inp.semantic_type,
                    value=param_value,
                )
            )

    return GoalSpec(
        goal_id=goal.goal_id,
        goal_type=goal.goal_type,
        desired_fact_types=goal.desired_fact_types,
        execution_mode=goal.execution_mode,
        goal_spec_version=goal.goal_spec_version,
        constraints=tuple(constraints),
    )


def compile_plan_v2(
    handoff: EscalationHandoff,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
) -> PlanCompileResult:
    """编译确定性 PlanGraph v2。不调用 LLM/Gateway/SAP。"""
    cards = discover_cards(snapshot, sources)
    raw_capabilities = _index_raw_capabilities(sources)
    goal = _build_goal_v2(handoff, cards)
    plan_graph = _build_plan_graph_v2(goal, snapshot, cards, raw_capabilities, handoff)
    gaps = _compute_gaps(goal, cards, _strip_v2_fields_for_gap_calc(plan_graph))

    graph = SemanticGraphCompiler().compile(sources)
    report = validate_plan_graph_v2(graph, snapshot, goal.to_dict(), plan_graph)

    n_nodes = len(plan_graph["nodes"])
    n_gaps = len(gaps)
    if not report.valid:
        flags = [Flag(_FLAG_INVALID_PLAN_GRAPH, _format_issues(report.issues))]
        rationale = (
            f"v2 validator failed: {len(report.issues)} issue(s); "
            f"compiled {n_nodes} node(s), {n_gaps} gap(s), 1 flag(s)"
        )
    else:
        flags = _compute_governance_flags_v2(plan_graph, cards)
        n_flags = len(flags)
        rationale = (
            f"v2 dry-run compiled {n_nodes} node(s), "
            f"{n_gaps} gap(s), {n_flags} flag(s)"
        )

    return PlanCompileResult(
        plan_graph=plan_graph,
        gaps=gaps,
        governance_flags=flags,
        projection_ref=list(plan_graph.get("projectionRef", [])),
        rule_set_refs=list(plan_graph.get("ruleSetRefs", [])),
        snapshot_id=snapshot.snapshot_id,
        rationale=rationale,
    )


def _build_plan_graph_v2(
    goal: GoalSpec,
    snapshot: RegistrySnapshot,
    cards: list[CapabilityCard],
    raw_capabilities: Mapping[str, Mapping[str, Any]],
    handoff: EscalationHandoff,
) -> dict[str, Any]:
    producers_by_fact = _index_producers_by_fact_type(cards)
    params_by_capability: dict[str, dict[str, Any]] = {}
    for matched in handoff.matched_intents:
        params_by_capability.setdefault(matched.capability_id, {}).update(
            matched.parameters
        )
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
            nodes.append(
                _build_node_v2(
                    card,
                    goal,
                    node_id,
                    raw,
                    params_by_capability.get(card.capability_id, {}),
                )
            )
        fact_type_to_node[fact_type] = node_id

    goal_outputs = [
        {"factTypeId": ft, "producerNodeId": nid}
        for ft, nid in fact_type_to_node.items()
    ]
    edges: list[dict[str, Any]] = []
    # Second pass: author factField sources + data edges for fact-bound inputs.
    # For each consumer node's required ``fact`` input, resolve the producer
    # node (from fact_type_to_node), find the producer output field whose
    # factTypeRef matches, and author a factField source binding + a 1:1
    # data edge (S1 validator requires EDGE_INCONSISTENT if missing/mismatched).
    data_edges: list[dict[str, Any]] = []
    edge_counter = 0
    cards_by_id = {c.capability_id: c for c in cards}
    for node in nodes:
        card = cards_by_id.get(node["capabilityId"])
        if card is None:
            continue
        for inp in card.inputs:
            if inp.binding_kind != "fact" or not inp.required:
                continue
            fact_type = inp.satisfiable_by_fact_type
            if fact_type is None:
                continue
            producer_node_id = fact_type_to_node.get(fact_type)
            if producer_node_id is None or producer_node_id == node["nodeId"]:
                continue
            producer_cap_id = next(
                n["capabilityId"] for n in nodes if n["nodeId"] == producer_node_id
            )
            producer_raw = raw_capabilities.get(producer_cap_id, {})
            field_name = _first_fact_field(producer_raw, fact_type)
            node["parameterBindings"].append(
                {
                    "parameterName": inp.name,
                    "source": {
                        "kind": "factField",
                        "producerNodeId": producer_node_id,
                        "factTypeId": fact_type,
                        "field": field_name,
                    },
                }
            )
            data_edges.append(
                {
                    "edgeId": f"edge.data.{edge_counter}",
                    "kind": "data",
                    "fromNodeId": producer_node_id,
                    "toNodeId": node["nodeId"],
                    "factTypeId": fact_type,
                }
            )
            edge_counter += 1

    edges.extend(data_edges)
    topological_order = _topological_order(node_ids, edges)

    read_partition, action_partition = _partition_nodes(nodes, raw_capabilities, topological_order)

    return {
        "planGraphVersion": 2,
        "planId": _plan_id_for(goal),
        "goalId": goal.goal_id,
        "executionMode": goal.execution_mode,
        "snapshotId": snapshot.snapshot_id,
        "nodes": nodes,
        "edges": edges,
        "topologicalOrder": topological_order,
        "goalOutputs": goal_outputs,
        "readPartition": read_partition,
        "actionPartition": action_partition,
        "projectionRef": [],
        "ruleSetRefs": [],
    }


def _build_node_v2(
    card: CapabilityCard,
    goal: GoalSpec,
    node_id: str,
    raw_capability: Mapping[str, Any],
    handoff_parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """v2 node: author goalConstraint + literal sources.

    factField sources are authored in ``_build_plan_graph_v2``'s second pass
    (they require cross-node producer resolution + raw output lookup that
    this function does not have access to).

    Parameter source authoring rules (identifier inputs, by priority):
    1. Matching GoalConstraint (name + semanticType) -> ``goalConstraint`` source
    2. Else has handoff parameter value -> ``literal`` source (semanticType
       from InputDescriptor, value from handoff parameter)
    3. Else required -> unbound (missing_parameter gap by _compute_gaps)

    Unlike v1, v2 attempts goalConstraint binding for ``identifier`` inputs
    regardless of ``required`` (user-supplied handoff values should get
    parameter provenance even for optional inputs), ensuring every produced
    node has a parameter source (v2 validator PARAMETER_SOURCE_MISSING only
    targets required inputs).
    """
    constraints_by_name = {c.name: c for c in goal.constraints}
    bindings: list[dict[str, Any]] = []
    params = handoff_parameters or {}
    for inp in card.inputs:
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
        elif (
            inp.binding_kind == "identifier"
            and inp.name in params
            and constraint is None
        ):
            # literal 源：semanticType 从 InputDescriptor 取，值从 handoff 参数取
            bindings.append(
                {
                    "parameterName": inp.name,
                    "source": {
                        "kind": "literal",
                        "semanticType": inp.semantic_type,
                        "value": params[inp.name],
                    },
                }
            )
        # factField sources are authored in _build_plan_graph_v2's second pass
    return {
        "nodeId": node_id,
        "capabilityId": card.capability_id,
        "parameterBindings": bindings,
        "producesFactTypes": sorted(card.produces_fact_types),
        "governance": _project_node_governance(raw_capability),
    }


def _topological_order(node_ids: list[str], edges: list[dict[str, Any]]) -> list[str]:
    """无 edge 时按 nodeId 排序（确定性）；有 edge 时按拓扑排序。Task 9 强化。"""
    return list(node_ids) if not edges else list(node_ids)


def _partition_nodes(
    nodes: list[dict[str, Any]],
    raw_capabilities: Mapping[str, Mapping[str, Any]],
    topological_order: list[str],
) -> tuple[list[str], list[str]]:
    """分区：read-only -> readPartition；其余 -> actionPartition。按 topologicalOrder 排序。"""
    from sap_nexus_agent.semantic_planning.validation import _is_read_only

    read: list[str] = []
    action: list[str] = []
    # 构造 capability -> nodeId 映射用于 _is_read_only（需 raw capability）
    node_by_id = {n["nodeId"]: n for n in nodes}
    for node_id in topological_order:
        node = node_by_id.get(node_id)
        if node is None:
            continue
        raw = raw_capabilities.get(node["capabilityId"], {})
        # 构造 S1 _is_read_only 期望的 capability 形状
        capability_view = {
            "kind": raw.get("kind", "Function"),
            "governance": raw.get("governance", {}),
        }
        if _is_read_only(capability_view):
            read.append(node_id)
        else:
            action.append(node_id)
    return read, action


def _compute_governance_flags_v2(
    plan_graph: dict[str, Any], cards: list[CapabilityCard]
) -> list[Flag]:
    """v2 governance flags：复用 v1 逻辑（write_side_effect/approval_required）。"""
    from sap_nexus_agent.planner.plan_compiler import _compute_governance_flags

    return _compute_governance_flags(plan_graph, cards)


def _strip_v2_fields_for_gap_calc(plan_graph: dict[str, Any]) -> dict[str, Any]:
    """_compute_gaps reads nodes/parameterBindings, v2 fields don't affect it."""
    return plan_graph


def _first_fact_field(
    producer_raw: Mapping[str, Any], fact_type: str
) -> str:
    """Find the first producer output field whose factTypeRef matches.

    Returns the output ``name``. The S1 ``_validate_parameter_source``
    validator checks ``output["name"] == source["field"]`` and
    ``output.get("factTypeRef") == source["factTypeId"]``. An empty string
    would fail schema ``minLength: 1`` -> ``FACT_TYPE_MISMATCH``; producers
    are expected to have a named output for the declared Fact Type.
    """
    for output in producer_raw.get("outputs", []):
        if output.get("factTypeRef") == fact_type and output.get("name"):
            return output["name"]
    return ""
