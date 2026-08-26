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

from sap_nexus_agent.governed_context import PlannerFailure
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
    _GAP_AMBIGUOUS_PRODUCER,
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


def _ambiguous_producer_fact_types(
    goal: GoalSpec, cards: list[CapabilityCard]
) -> dict[str, tuple[str, ...]]:
    """Desired Fact Types with more than one active producer (T2 task 3.4.4).

    The single authority for that judgement: ``_build_plan_graph_v2`` refuses to
    author a node from these, and ``compile_plan_v2`` records the matching
    ``ambiguous_producer`` gap. Deriving it twice would let the graph and the
    gap list disagree — a plan silently missing a node with nothing recorded is
    worse than no plan at all.

    Latent while every Fact Type has exactly one producer, load-bearing once the
    planner auto-pulls producers in: ``producers[0]`` would then pick a *SAP
    call* by list order.

    Candidate order is inherited from ``_index_producers_by_fact_type``, which
    already sorts by ``capability_id``. Re-sorting here would be a second
    authority for the same ordering — and one no test could tell apart.
    """
    producers_by_fact = _index_producers_by_fact_type(cards)
    ambiguous: dict[str, tuple[str, ...]] = {}
    for fact_type in goal.desired_fact_types:
        producers = producers_by_fact.get(fact_type) or []
        if len(producers) > 1:
            ambiguous[fact_type] = tuple(card.capability_id for card in producers)
    return ambiguous


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
    if handoff.registry_snapshot_id != snapshot.snapshot_id:
        raise PlannerFailure(
            error_type="SNAPSHOT_DRIFT",
            message=(
                f"snapshot drift: handoff={handoff.registry_snapshot_id} "
                f"!= snapshot={snapshot.snapshot_id}"
            ),
            snapshot_id=snapshot.snapshot_id,
            audit_evidence={
                "expected_snapshot_id": snapshot.snapshot_id,
                "actual_snapshot_id": handoff.registry_snapshot_id,
                "stage": "compile_plan_v2",
            },
        )
    cards = discover_cards(snapshot, sources)
    raw_capabilities = _index_raw_capabilities(sources)
    goal = _build_goal_v2(handoff, cards)
    plan_graph = _build_plan_graph_v2(goal, snapshot, cards, raw_capabilities, handoff, sources)
    gaps = _compute_gaps(goal, cards, _strip_v2_fields_for_gap_calc(plan_graph))
    # T2 task 3.4.4. Recorded here rather than in the shared ``_compute_gaps``:
    # the v1 compiler shares that function but still authors ``producers[0]``,
    # so reporting the gap there would give v1 a gap next to the arbitrary node
    # it went ahead and built.
    for fact_type, candidates in sorted(
        _ambiguous_producer_fact_types(goal, cards).items()
    ):
        gaps.append(
            Gap(
                _GAP_AMBIGUOUS_PRODUCER,
                f"{fact_type}: {len(candidates)} active producers "
                f"({', '.join(candidates)}); registry must disambiguate",
            )
        )

    gaps.extend(_derivation_diagnostic_gaps(sources, plan_graph))

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
    sources: SemanticSourceDocuments,
) -> dict[str, Any]:
    producers_by_fact = _index_producers_by_fact_type(cards)
    ambiguous_fact_types = _ambiguous_producer_fact_types(goal, cards)
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
        if fact_type in ambiguous_fact_types:
            # T2 task 3.4.4: more than one active producer. Authoring
            # ``producers[0]`` would resolve a registry ambiguity by list order.
            # ``compile_plan_v2`` records the ``ambiguous_producer`` gap for the
            # same Fact Types, so the omission is never silent.
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
    # Second pass: author factField sources + data edges for inputs that
    # declare ``satisfiableByFactType`` (regardless of ``bindingKind``).
    # For each such required input, resolve the producer node (from
    # fact_type_to_node), find the producer output field whose factTypeRef
    # matches, and author a factField source binding + a 1:1 data edge
    # (S1 validator requires EDGE_INCONSISTENT if missing/mismatched).
    data_edges: list[dict[str, Any]] = []
    # T3 task 5.5 (defect 1). A ``data`` edge identifies the
    # ``(producer, consumer, factType)`` triple, not the individual binding, so
    # two derived parameters drawn from one upstream Fact share one edge. The
    # validator agrees on both halves: ``expected_data[key]`` is a list of
    # source paths, and duplicate edges for one key are ``EDGE_INCONSISTENT``.
    data_edge_keys: set[tuple[str, str, str]] = set()
    edge_counter = 0
    cards_by_id = {c.capability_id: c for c in cards}
    # Verify-phase finding R10. The deriver is the field-selection authority
    # (proposal finding F1), and it refuses an input whose only candidate field is
    # ``cardinality: many`` -- choosing a reduction operator is not the planner's
    # decision. This pass matched on ``factTypeRef`` + ``semanticType`` only and
    # never consulted cardinality, so it bound a list field to a scalar input that
    # the deriver had already diagnosed as ``needsReduction``. Two components
    # deciding one thing by different rules, the same shape as finding R1.
    diagnosed_inputs = _diagnosed_consumer_inputs(sources)
    for node in nodes:
        card = cards_by_id.get(node["capabilityId"])
        if card is None:
            continue
        # User-supplied beats upstream-derived: precedence is applied at
        # authoring time, so exactly one source is authored per parameter and
        # the duplicate-``parameterBindings`` hazard cannot arise.
        already_bound = {
            binding["parameterName"]
            for binding in node["parameterBindings"]
            if binding["source"]["kind"]
            in (_SOURCE_KIND_GOAL_CONSTRAINT, "literal")
        }
        for inp in card.inputs:
            if not inp.satisfiable_by_fact_type or not inp.required:
                continue
            if inp.name in already_bound:
                continue
            if (node["capabilityId"], inp.name) in diagnosed_inputs:
                # The deriver reported needsReduction / ambiguous for this input.
                # Leaving it unbound is the point: the gap explains why, and a
                # bound-but-wrong value would be worse than an absent one.
                continue
            fact_type = inp.satisfiable_by_fact_type
            producer_node_id = fact_type_to_node.get(fact_type)
            if producer_node_id is None or producer_node_id == node["nodeId"]:
                continue
            producer_cap_id = next(
                n["capabilityId"] for n in nodes if n["nodeId"] == producer_node_id
            )
            producer_raw = raw_capabilities.get(producer_cap_id, {})
            field_name = _fact_field_for_input(
                producer_raw, fact_type, inp.semantic_type, inp.binding_kind
            )
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
            data_edge_key = (producer_node_id, node["nodeId"], fact_type)
            if data_edge_key in data_edge_keys:
                continue
            data_edge_keys.add(data_edge_key)
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

    # T3 task 5.4b: give an auto-pulled producer its own key inputs.
    #
    # The closure (task 5.4) puts the producer node into the plan and the pass
    # above binds the *consumer's* parameters from it, but the producer's own
    # required inputs came from ``handoff.matched_intents`` and an auto-pulled
    # producer was never matched — so it had zero bindings and the plan carried
    # ``invalid_plan_graph``. Found by computing 6.1's table, not by review.
    #
    # The rule is registry-driven: a producer input may be filled from the
    # consumer only when its ``semanticType`` is one of the produced Fact Type's
    # ``keyedBy`` types. That is what makes the pulled read *the same* material's
    # info rather than an arbitrary same-typed value, and it keeps an unrelated
    # required input unbound so it still fails closed.
    _propagate_keys_to_pulled_producers(
        nodes, cards_by_id, fact_type_to_node, data_edges, sources
    )

    # Third pass: author dependency edges from dependsOn relations.
    # For each snapshot dependsOn relation where both capabilities are in
    # the plan, author a ``dependency`` edge (fromNodeId=prerequisite,
    # toNodeId=dependent). The S1 validator requires exactly one dependency
    # edge per expected dependsOn (EDGE_INCONSISTENT if missing).
    dependency_edges: list[dict[str, Any]] = []
    cap_to_node = {n["capabilityId"]: n["nodeId"] for n in nodes}
    relations = sources.relations.get("relations", []) if hasattr(sources, "relations") else []
    dep_edge_counter = edge_counter
    for relation in relations:
        if relation.get("relationType") != "dependsOn":
            continue
        dependent_cap = relation.get("capabilityId")
        prerequisite_cap = relation.get("dependsOnCapabilityId")
        if dependent_cap not in cap_to_node or prerequisite_cap not in cap_to_node:
            continue
        dependency_edges.append({
            "edgeId": f"edge.dep.{dep_edge_counter}",
            "kind": "dependency",
            "fromNodeId": cap_to_node[prerequisite_cap],
            "toNodeId": cap_to_node[dependent_cap],
        })
        dep_edge_counter += 1
    edges.extend(dependency_edges)

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


def _diagnosed_consumer_inputs(
    sources: SemanticSourceDocuments,
) -> frozenset[tuple[str, str]]:
    """``(capabilityId, inputName)`` pairs the deriver refused to resolve.

    Verify-phase finding R10. Shared by the binding pass and the gap pass so the
    plan cannot both bind an input and report it as unresolved.
    """
    try:
        from sap_nexus_agent.semantic_planning.derivation import (
            derive_data_dependencies,
        )

        diagnostics = derive_data_dependencies(sources).diagnostics
    except Exception:  # noqa: BLE001 - fail open on binding, the gap pass reports
        return frozenset()
    return frozenset(
        (diagnostic.consumer_capability_id, diagnostic.consumer_input_name)
        for diagnostic in diagnostics
    )


def _derivation_diagnostic_gaps(
    sources: SemanticSourceDocuments,
    plan_graph: Mapping[str, Any],
) -> list[Gap]:
    """Surface the deriver's per-input diagnostics as dry-run gaps.

    T5 verify-phase finding R9. ``needsReduction`` and ``ambiguous`` existed only
    inside ``derive_data_dependencies(...).diagnostics``, so an input the deriver
    deliberately refused to bind was simply *absent* from the plan with nothing
    explaining why. A reader could not tell "no producer publishes this" from "a
    producer does, but its field is a list and choosing a reduction operator is
    not the planner's decision".

    Distinct from ``ambiguous_producer``, which is per desired Fact Type with
    several producer *capabilities*. These are per consuming *input*.

    Scoped to capabilities actually in this plan: the deriver reports over the
    whole registry, and a gap about a capability the user never invoked would be
    noise attached to the wrong run. The diagnostic names its candidates, because
    "this input is unresolved" without them sends the reader back to the registry.
    """
    capability_ids = {
        node.get("capabilityId") for node in plan_graph.get("nodes", ())
    }
    if not capability_ids:
        return []
    try:
        from sap_nexus_agent.semantic_planning.derivation import (
            derive_data_dependencies,
        )

        diagnostics = derive_data_dependencies(sources).diagnostics
    except Exception:  # noqa: BLE001 - a dry run must not fail on a report
        return []
    return [
        Gap(
            diagnostic.kind,
            f"{diagnostic.consumer_capability_id}.{diagnostic.consumer_input_name}: "
            f"{diagnostic.candidate_kind} candidates "
            f"({', '.join(diagnostic.candidates)}) for "
            f"{diagnostic.fact_type_id} / {diagnostic.semantic_type}",
        )
        for diagnostic in diagnostics
        if diagnostic.consumer_capability_id in capability_ids
    ]


def _keyed_by_semantic_types(
    sources: SemanticSourceDocuments, fact_type_id: str
) -> frozenset[str]:
    """The semantic types that identify one instance of ``fact_type_id``.

    Read from ``ontology/fact-types.yaml``'s ``keyedBy``, which is already
    governed: every entry must be a tier-1 value type
    (``_validate_vocabulary_references``). Returns an empty set for an unknown
    Fact Type, which makes the caller propagate nothing rather than guess.
    """
    for fact_type in sources.fact_types.get("factTypes", ()) or ():
        if fact_type.get("factTypeId") == fact_type_id:
            return frozenset(fact_type.get("keyedBy") or ())
    return frozenset()


def _propagate_keys_to_pulled_producers(
    nodes: list[dict[str, Any]],
    cards_by_id: Mapping[str, CapabilityCard],
    fact_type_to_node: Mapping[str, str],
    data_edges: list[dict[str, Any]],
    sources: SemanticSourceDocuments,
) -> None:
    """Bind a pulled producer's key inputs from the consumer that pulled it.

    T3 task 5.4b. Only ``literal`` and ``goalConstraint`` sources are copied:
    those are the values the user actually supplied. A ``factField`` source is
    deliberately not chained, because copying one derived value into another
    node's input would make the plan depend on an execution order the data edges
    do not express.

    Mutates ``nodes`` in place, matching how the surrounding passes are written.
    """
    nodes_by_id = {node["nodeId"]: node for node in nodes}
    for edge in data_edges:
        producer = nodes_by_id.get(edge["fromNodeId"])
        consumer = nodes_by_id.get(edge["toNodeId"])
        if producer is None or consumer is None:
            continue
        producer_card = cards_by_id.get(producer["capabilityId"])
        if producer_card is None:
            continue
        keyed_by = _keyed_by_semantic_types(sources, edge["factTypeId"])
        if not keyed_by:
            continue
        consumer_card = cards_by_id.get(consumer["capabilityId"])
        if consumer_card is None:
            continue
        consumer_types = {inp.name: inp.semantic_type for inp in consumer_card.inputs}
        supplied: dict[str, dict[str, Any]] = {}
        for binding in consumer["parameterBindings"]:
            if binding["source"]["kind"] not in (
                _SOURCE_KIND_GOAL_CONSTRAINT,
                "literal",
            ):
                continue
            semantic_type = consumer_types.get(binding["parameterName"])
            if semantic_type is not None:
                supplied.setdefault(semantic_type, binding["source"])
        bound = {b["parameterName"] for b in producer["parameterBindings"]}
        for inp in producer_card.inputs:
            if not inp.required or inp.name in bound:
                continue
            if inp.semantic_type not in keyed_by:
                continue
            source = supplied.get(inp.semantic_type)
            if source is None:
                continue
            producer["parameterBindings"].append(
                {"parameterName": inp.name, "source": dict(source)}
            )


def _topological_order(node_ids: list[str], edges: list[dict[str, Any]]) -> list[str]:
    """无 edge 时按 nodeId 顺序（确定性）；有 edge 时按 Kahn 拓扑排序。

    Kahn's algorithm with a sorted ready-queue for deterministic output.
    Respects both data edges (producer -> consumer) and dependency edges
    (prerequisite -> dependent): for every edge, ``fromNodeId`` appears
    before ``toNodeId`` in the result, satisfying the S1 validator's
    ``_validate_topological_order`` constraint.

    No edges -> fall back to ``list(node_ids)`` (insertion order, deterministic).
    Cycle fallback -> append unprocessed nodes in sorted order (defensive;
    cycles are caught by the S1 validator, not by this function).
    """
    if not edges:
        return list(node_ids)

    node_set = set(node_ids)
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}

    for edge in edges:
        frm = edge["fromNodeId"]
        to = edge["toNodeId"]
        if frm in node_set and to in node_set:
            adj[frm].append(to)
            in_degree[to] += 1

    # Kahn's algorithm: always pop the lexicographically smallest ready node
    # so the output is deterministic across runs.
    ready = sorted(nid for nid in node_ids if in_degree[nid] == 0)
    result: list[str] = []

    while ready:
        node = ready.pop(0)
        result.append(node)
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                ready.append(neighbor)
        ready.sort()

    # Cycle fallback: append unprocessed nodes in sorted order (defensive).
    if len(result) < len(node_ids):
        result.extend(sorted(nid for nid in node_ids if nid not in set(result)))

    return result


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


def _fact_field_for_input(
    producer_raw: Mapping[str, Any],
    fact_type: str,
    semantic_type: str,
    binding_kind: str,
) -> str:
    """Find the producer output field that satisfies one consumer input.

    Returns the output ``name``. The S1 ``_validate_parameter_source``
    validator checks ``output["name"] == source["field"]`` and
    ``output.get("factTypeRef") == source["factTypeId"]``. An empty string
    fails schema ``minLength: 1`` -> ``FACT_TYPE_MISMATCH``, which is the
    intended outcome when nothing satisfies the input.

    T3 task 5.6. Per correction C3 a Fact Type's fields are published as
    *several* outputs sharing one ``factTypeRef``, so matching on
    ``factTypeRef`` alone picks an arbitrary one. The two ``bindingKind``
    tiers are told apart because their ``semanticType`` means different
    things (correction C8):

    - ``identifier`` wants one value, and its ``semanticType`` is a tier-1
      value type, so that is the discriminator. No match is a real failure.
    - ``fact`` wants the Fact as a whole, and its ``semanticType`` is a
      tier-2 Fact Type id, so there is nothing to discriminate on: the first
      matching output is the Fact's representative field.
    """
    matching = [
        output
        for output in producer_raw.get("outputs", [])
        if output.get("factTypeRef") == fact_type and output.get("name")
    ]
    if binding_kind == _IDENTIFIER_BINDING_KIND:
        for output in matching:
            if output.get("semanticType") == semantic_type:
                return output["name"]
        return ""
    return matching[0]["name"] if matching else ""
