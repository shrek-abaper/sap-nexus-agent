"""Deterministic compiler: resolved goal -> READ_ONLY plan + analysis DAG.

The read half is a legal PlanGraph v2 (validated by the unchanged
``validate_plan_graph_v2``); the analysis half is a separate registered-
operator DAG. Operators never masquerade as SAP capabilities.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from sap_nexus_agent.planner.capability_card import discover_cards
from sap_nexus_agent.semantic_planning.snapshot import canonical_json_bytes

from .bounds import BOUNDS


class CompilerFailure(RuntimeError):
    """The resolved goal cannot be compiled into a legal plan."""


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _raw_capabilities(sources: Any) -> dict[str, dict[str, Any]]:
    return {
        item["capabilityId"]: item
        for item in sources.capabilities.get("capabilities", [])
    }


def _assert_read_only(capability_ids: set[str], raw: dict[str, dict[str, Any]]) -> None:
    for capability_id in sorted(capability_ids):
        definition = raw.get(capability_id)
        if definition is None:
            raise CompilerFailure(f"capability not in registry: {capability_id}")
        if definition.get("kind") != "Function":
            raise CompilerFailure(
                f"non-Function capability in read plan: {capability_id}"
            )
        governance = definition.get("governance", {})
        if governance.get("sideEffect", "none") != "none":
            raise CompilerFailure(f"WRITE rejected pre-Gateway: {capability_id}")
        if governance.get("requiresApproval", False):
            raise CompilerFailure(
                f"approval-bearing capability rejected: {capability_id}"
            )


def _goal_constraint_names(
    cards_by_id: dict[str, Any], capability_ids: list[str], supplied: dict[str, str]
) -> set[str]:
    counts: dict[str, set[str]] = defaultdict(set)
    for capability_id in capability_ids:
        card = cards_by_id.get(capability_id)
        if card is None:
            continue
        for descriptor in card.inputs:
            if descriptor.binding_kind == "identifier" and descriptor.name in supplied:
                counts[descriptor.name].add(capability_id)
    return {name for name, caps in counts.items() if len(caps) >= 2}


def _author_nodes(
    capability_ids: list[str],
    cards_by_id: dict[str, Any],
    raw: dict[str, dict[str, Any]],
    supplied: dict[str, str],
    closure: tuple[Any, ...],
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    # Pre-map node ids so factField producer refs resolve regardless of
    # alphabetic authoring order.
    node_by_cap = {
        capability_id: f"read-{index}"
        for index, capability_id in enumerate(capability_ids)
    }
    constraint_names = _goal_constraint_names(
        cards_by_id, capability_ids, supplied
    )
    fact_bindings_by_consumer: dict[str, dict[str, Any]] = defaultdict(dict)
    for binding in closure:
        fact_bindings_by_consumer[binding.consumer_capability_id][
            binding.consumer_input_name
        ] = binding

    nodes: list[dict[str, Any]] = []
    for capability_id in capability_ids:
        card = cards_by_id[capability_id]
        bindings: list[dict[str, Any]] = []

        for descriptor in card.inputs:
            derived = fact_bindings_by_consumer.get(capability_id, {}).get(
                descriptor.name
            )
            if derived is not None:
                producer_node = node_by_cap[derived.producer_capability_id]
                bindings.append({
                    "parameterName": descriptor.name,
                    "source": {
                        "kind": "factField",
                        "producerNodeId": producer_node,
                        "factTypeId": derived.fact_type_id,
                        "field": derived.fact_field_name,
                    },
                })
                continue
            if descriptor.name not in supplied:
                continue
            if descriptor.name in constraint_names:
                bindings.append({
                    "parameterName": descriptor.name,
                    "source": {
                        "kind": "goalConstraint",
                        "constraintName": descriptor.name,
                    },
                })
            else:
                bindings.append({
                    "parameterName": descriptor.name,
                    "source": {
                        "kind": "literal",
                        "semanticType": descriptor.semantic_type,
                        "value": supplied[descriptor.name],
                    },
                })

        raw_definition = raw[capability_id]
        governance = raw_definition.get("governance", {})
        nodes.append({
            "nodeId": node_by_cap[capability_id],
            "capabilityId": capability_id,
            "parameterBindings": bindings,
            "producesFactTypes": sorted(card.produces_fact_types),
            "governance": {
                "capabilityKind": raw_definition.get("kind", "Function"),
                "sideEffect": governance.get("sideEffect", "none"),
                "requiresApproval": governance.get("requiresApproval", False),
                "approvalPolicy": governance.get("approvalPolicy", "not_required"),
            },
        })

    data_edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str]] = set()
    for binding in closure:
        producer_node = node_by_cap.get(binding.producer_capability_id)
        consumer_node = node_by_cap.get(binding.consumer_capability_id)
        if producer_node is None or consumer_node is None:
            continue
        key = (producer_node, consumer_node, binding.fact_type_id)
        if key in edge_keys:
            continue
        edge_keys.add(key)
        data_edges.append({
            "edgeId": f"edge.data.{len(data_edges)}",
            "kind": "data",
            "fromNodeId": producer_node,
            "toNodeId": consumer_node,
            "factTypeId": binding.fact_type_id,
        })
    return nodes, node_by_cap, data_edges


def _topological_order(node_ids: list[str], edges: list[dict[str, Any]]) -> list[str]:
    incoming: dict[str, set[str]] = {n: set() for n in node_ids}
    for edge in edges:
        if edge["toNodeId"] in incoming and edge["fromNodeId"] in incoming:
            incoming[edge["toNodeId"]].add(edge["fromNodeId"])
    order: list[str] = []
    done: set[str] = set()
    remaining = list(node_ids)
    while remaining:
        progressed = False
        for node_id in list(remaining):
            if incoming[node_id] <= done:
                order.append(node_id)
                done.add(node_id)
                remaining.remove(node_id)
                progressed = True
        if not progressed:
            raise CompilerFailure("cycle in read plan data edges")
    return order


def _analysis_dag(draft: Any, pinned: Any) -> dict[str, Any]:
    nodes = list(draft.analysis_nodes)
    if len(nodes) > BOUNDS.max_analysis_nodes:
        raise CompilerFailure("too many analysis nodes")
    ids = [n.node_id for n in nodes]
    if len(set(ids)) != len(ids):
        raise CompilerFailure("duplicate analysis node ids")

    allowlist = pinned.allowlist_fields
    planned: list[dict[str, Any]] = []
    state: dict[str, int] = {}

    def visit(node_id: str) -> None:
        if state.get(node_id) == 1:
            raise CompilerFailure("cycle in analysis DAG")
        if state.get(node_id) == 2:
            return
        state[node_id] = 1
        node = next(n for n in nodes if n.node_id == node_id)
        if node.operator_id not in pinned.operators:
            raise CompilerFailure(f"unknown operator: {node.operator_id}")
        for dep in node.depends_on:
            if dep not in ids:
                raise CompilerFailure(
                    f"analysis node depends on unknown node: {dep}"
                )
            visit(dep)
        for input_ref in node.inputs:
            kind = input_ref.get("kind")
            if kind == "factField":
                fact_type = input_ref.get("factTypeId")
                field = input_ref.get("field")
                if field not in allowlist.get(fact_type, frozenset()):
                    raise CompilerFailure(
                        f"analysis input not allowed: {fact_type}.{field}"
                    )
            elif kind == "nodeRef":
                if input_ref.get("nodeId") not in ids:
                    raise CompilerFailure("analysis nodeRef unresolved")
            else:
                raise CompilerFailure(
                    "analysis input kind must be factField|nodeRef"
                )
        state[node_id] = 2
        planned.append({
            "nodeId": node.node_id,
            "operatorId": node.operator_id,
            "operatorVersion": pinned.operator_versions[node.operator_id],
            "inputs": [dict(i) for i in node.inputs],
            "params": dict(node.params),
            "definitionRefs": [],
            "dependsOn": list(node.depends_on),
        })

    for node in nodes:
        visit(node.node_id)

    has_dependents = {dep for n in nodes for dep in n.depends_on}
    outputs = [n.node_id for n in nodes if n.node_id not in has_dependents]
    return {"nodes": planned, "outputs": outputs}


def goal_spec_for(plan: dict[str, Any]) -> dict[str, Any]:
    """The GoalSpec dict used to validate the readPlan."""
    return plan["goalSpec"]


def compile(
    draft: Any,
    resolution: Any,
    pinned: Any,
    sources: Any,
    snapshot: Any,
    graph: Any,
    principal: dict[str, Any],
    scope: dict[str, str],
) -> dict[str, Any]:
    if resolution.status != "complete":
        raise CompilerFailure(
            f"cannot compile resolution with status {resolution.status}"
        )

    raw = _raw_capabilities(sources)
    cards = discover_cards(snapshot, sources)
    cards_by_id = {card.capability_id: card for card in cards}

    desired_caps = [fact.producer_capability_id for fact in resolution.desired]
    capability_ids = sorted(
        set(desired_caps) | set(resolution.closure_capabilities)
    )
    _assert_read_only(set(capability_ids), raw)

    supplied: dict[str, str] = {}
    for fact in resolution.desired:
        for selector in fact.selectors:
            supplied.setdefault(selector["key"], selector["value"])
    for constraint in draft.constraints:
        supplied.setdefault(constraint.name, constraint.value)

    if len(capability_ids) > BOUNDS.max_read_nodes:
        raise CompilerFailure("too many read nodes")

    nodes, node_by_cap, data_edges = _author_nodes(
        capability_ids, cards_by_id, raw, supplied, resolution.closure
    )
    node_ids = [n["nodeId"] for n in nodes]
    order = _topological_order(node_ids, data_edges)

    desired_fact_types = sorted({f.fact_type_id for f in resolution.desired})
    goal_constraint_names = {
        binding["parameterName"]
        for node in nodes
        for binding in node["parameterBindings"]
        if binding["source"]["kind"] == "goalConstraint"
    }
    semantic_types: dict[str, str] = {}
    for capability_id in capability_ids:
        for descriptor in cards_by_id[capability_id].inputs:
            semantic_types.setdefault(descriptor.name, descriptor.semantic_type)
    constraints = [
        {
            "name": name,
            "semanticType": semantic_types[name],
            "value": supplied[name],
        }
        for name in sorted(goal_constraint_names)
    ]
    goal_id = "ont:" + _sha256(
        {"facts": desired_fact_types, "constraints": constraints}
    )[7:20]
    goal_spec = {
        "goalSpecVersion": 1,
        "goalId": goal_id,
        "goalType": "dynamic-read-analysis",
        "executionMode": "READ_ONLY",
        "desiredFactTypes": desired_fact_types,
        "constraints": constraints,
    }

    analysis_plan = _analysis_dag(draft, pinned)

    goal_outputs = [
        {
            "factTypeId": fact.fact_type_id,
            "producerNodeId": node_by_cap[fact.producer_capability_id],
        }
        for fact in sorted(resolution.desired, key=lambda f: f.fact_type_id)
    ]

    read_plan = {
        "planGraphVersion": 2,
        "planId": "read-" + _sha256({"goal": goal_id, "nodes": node_ids})[7:24],
        "goalId": goal_id,
        "executionMode": "READ_ONLY",
        "snapshotId": snapshot.snapshot_id,
        "nodes": nodes,
        "edges": data_edges,
        "topologicalOrder": order,
        "goalOutputs": goal_outputs,
        "readPartition": node_ids,
        "actionPartition": [],
        "projectionRef": [],
        "ruleSetRefs": [],
    }

    plan_body = {
        "readPlan": read_plan,
        "analysisPlan": analysis_plan,
        "scope": scope,
    }
    return {
        "schemaVersion": 1,
        "planId": _sha256(plan_body),
        "semanticSnapshotId": pinned.package.semantic_snapshot_id,
        "registrySnapshotId": snapshot.snapshot_id,
        "principalId": principal.get("principalId", "local-user-0001"),
        "scope": scope,
        "readPlan": read_plan,
        "analysisPlan": analysis_plan,
        "goalSpec": goal_spec,
        "limits": {
            "maxReadNodes": BOUNDS.max_read_nodes,
            "maxAnalysisNodes": BOUNDS.max_analysis_nodes,
            "maxDepth": BOUNDS.max_depth,
            "overallTimeoutSeconds": BOUNDS.overall_timeout_seconds,
            "maxRows": BOUNDS.max_rows,
            "maxResponseBytes": BOUNDS.max_response_bytes,
        },
        "freshness": {},
        "coverage": {
            "covered": [c.id for c in draft.requested_conclusions],
            "uncovered": [],
        },
    }
