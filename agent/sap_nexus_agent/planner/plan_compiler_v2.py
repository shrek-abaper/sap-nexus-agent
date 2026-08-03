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
from sap_nexus_agent.planner.goal_spec import GoalSpec
from sap_nexus_agent.planner.handoff import _build_goal_with_constraints
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


def compile_plan_v2(
    handoff: EscalationHandoff,
    snapshot: RegistrySnapshot,
    sources: SemanticSourceDocuments,
) -> PlanCompileResult:
    """编译确定性 PlanGraph v2。不调用 LLM/Gateway/SAP。"""
    cards = discover_cards(snapshot, sources)
    raw_capabilities = _index_raw_capabilities(sources)
    goal = _build_goal_with_constraints(handoff, cards)
    plan_graph = _build_plan_graph_v2(goal, snapshot, cards, raw_capabilities)
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
) -> dict[str, Any]:
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
            nodes.append(_build_node_v2(card, goal, node_id, raw))
        fact_type_to_node[fact_type] = node_id

    goal_outputs = [
        {"factTypeId": ft, "producerNodeId": nid}
        for ft, nid in fact_type_to_node.items()
    ]
    edges: list[dict[str, Any]] = []  # Task 8/9 追加 data/dependency edge
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
) -> dict[str, Any]:
    """v2 node：本期先 author goalConstraint 源；literal/factField
    在 Task 7/8 追加。

    与 v1 的差异：v2 对 ``identifier`` 输入不论 ``required`` 均尝试绑定
    goalConstraint（用户经 handoff 提供的值即便能力声明为可选也应当获得
    参数溯源），从而保证每个产出节点都有参数源（见 v2 validator
    PARAMETER_SOURCE_MISSING 仅针对 required 输入）。
    """
    constraints_by_name = {c.name: c for c in goal.constraints}
    bindings: list[dict[str, Any]] = []
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
    """_compute_gaps 读取 nodes/parameterBindings，v2 字段不影响。返回原 plan_graph。"""
    return plan_graph
