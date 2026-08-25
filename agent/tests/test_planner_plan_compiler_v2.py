from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

import pytest

from sap_nexus_agent.governed_context import PlannerFailure
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


# ---- Task 1.3: user-supplied beats upstream-derived (authoring-time precedence) ----
#
# Requirement: openspec/changes/derived-parameter-binding/specs/
# semantic-plan-authoring-v2/spec.md — a value the user stated explicitly must
# not be overwritten by, or duplicated with, an upstream-derived one. Precedence
# is applied at *authoring* time, so exactly one source is authored per
# parameter and the duplicate-parameterBindings hazard cannot arise.


def _sources_with_derivable_identifier() -> tuple[
    SemanticSourceDocuments, RegistrySnapshot
]:
    """Consumer with an ``identifier`` input that declares
    ``satisfiableByFactType``, i.e. a parameter that *may* be derived from an
    upstream Fact but is still an identifier the user can simply state.

    The producer (``MM.Inventory.GetAvailability``) publishes
    ``availableQuantity`` / ``sapnexus:AvailableQuantity`` on
    ``sapnexus:InventoryAvailabilityFact``, so the consumer input's semantic
    type matches a real producer output field.
    """
    base = _real_sources()
    caps = _unfreeze(base.capabilities)
    facts = _unfreeze(base.fact_types)
    caps["capabilities"].append({
        "capabilityId": "Test.Consumer.UseQuantity",
        "name": "Test Quantity Consumer",
        "description": "Consumes a quantity that may be derived upstream",
        "domain": "MM",
        "businessObject": "Test",
        "ontologyIri": "sapnexus:Test_Quantity_Consumer",
        "semanticType": "sapnexus:TestQuantityConsumerReadFunction",
        "aliases": [],
        "status": "active",
        "kind": "Function",
        "inputs": [
            {
                "name": "quantity",
                "semanticType": "sapnexus:AvailableQuantity",
                "required": True,
                "bindingKind": "identifier",
                "satisfiableByFactType": "sapnexus:InventoryAvailabilityFact",
                "type": "string",
            }
        ],
        "outputs": [
            {"name": "summary", "factTypeRef": "sapnexus:TestQuantitySummaryFact"}
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
    facts["factTypes"].append(
        {"factTypeId": "sapnexus:TestQuantitySummaryFact", "fields": []}
    )
    sources = SemanticSourceDocuments(
        capabilities=caps,
        executor_bindings=base.executor_bindings,
        fact_types=facts,
        relations=base.relations,
    )
    return sources, build_registry_snapshot(sources)


def _quantity_handoff(snapshot, consumer_parameters) -> EscalationHandoff:
    return EscalationHandoff(
        reason="precedence",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "M1", "plant": "5300"},
                missing=[],
            ),
            MatchedIntent(
                capability_id="Test.Consumer.UseQuantity",
                parameters=consumer_parameters,
                missing=[],
            ),
        ],
        utterance="quantity precedence",
        registry_snapshot_id=snapshot.snapshot_id,
    )


def _bindings_for(plan_graph, capability_id, parameter_name):
    node = next(
        n for n in plan_graph["nodes"] if n["capabilityId"] == capability_id
    )
    return [
        b for b in node["parameterBindings"] if b["parameterName"] == parameter_name
    ]


def test_unsupplied_derivable_identifier_is_authored_as_fact_field():
    """Control: with the value absent, the compiler DOES derive it."""
    sources, snapshot = _sources_with_derivable_identifier()
    result = compile_plan_v2(_quantity_handoff(snapshot, {}), snapshot, sources)

    bindings = _bindings_for(
        result.plan_graph, "Test.Consumer.UseQuantity", "quantity"
    )
    assert [b["source"]["kind"] for b in bindings] == ["factField"]
    data_edges = [e for e in result.plan_graph["edges"] if e["kind"] == "data"]
    assert len(data_edges) == 1


def test_user_supplied_value_suppresses_the_fact_field_source():
    """User-supplied beats upstream-derived, even though the producer node is
    present in the plan and the Fact Type is available."""
    sources, snapshot = _sources_with_derivable_identifier()
    result = compile_plan_v2(
        _quantity_handoff(snapshot, {"quantity": "17"}), snapshot, sources
    )

    bindings = _bindings_for(
        result.plan_graph, "Test.Consumer.UseQuantity", "quantity"
    )
    # Exactly one source, and it is the user's — not a second, derived one.
    assert len(bindings) == 1
    assert bindings[0]["source"]["kind"] in {"literal", "goalConstraint"}
    assert not [
        e
        for e in result.plan_graph["edges"]
        if e["kind"] == "data"
        and e["factTypeId"] == "sapnexus:InventoryAvailabilityFact"
        and e["toNodeId"]
        == next(
            n["nodeId"]
            for n in result.plan_graph["nodes"]
            if n["capabilityId"] == "Test.Consumer.UseQuantity"
        )
    ], "no data edge may be authored for a parameter the user supplied"


# ---- Task 9: dependency edge authoring + topological sort ----


def _sources_with_depends_on() -> tuple[SemanticSourceDocuments, RegistrySnapshot]:
    """Construct a custom sources with a dependsOn relation.

    The consumer ``Test.Consumer.GetSummary`` has **no fact input** (empty
    inputs) to isolate the dependency edge from data edges. It produces
    ``sapnexus:TestSummaryFact`` so it is included in the plan via
    ``desired_fact_types``. A ``dependsOn`` relation declares it depends on
    ``MM.Inventory.GetAvailability`` (prerequisite).
    """
    base = _real_sources()
    caps = _unfreeze(base.capabilities)
    facts = _unfreeze(base.fact_types)
    relations = _unfreeze(base.relations)
    # Consumer with no fact input (pure dependsOn, no data edge).
    caps["capabilities"].append({
        "capabilityId": "Test.Consumer.GetSummary",
        "name": "Test Consumer",
        "description": "Depends on inventory availability",
        "domain": "MM",
        "businessObject": "Test",
        "ontologyIri": "sapnexus:Test_Consumer",
        "semanticType": "sapnexus:TestConsumerReadFunction",
        "aliases": [],
        "status": "active",
        "kind": "Function",
        "inputs": [],
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
    # Test.Consumer.GetSummary dependsOn MM.Inventory.GetAvailability
    relations["relations"].append({
        "relationId": "rel.test.dependsOn",
        "relationType": "dependsOn",
        "origin": "manual",
        "justification": "fixture-authored relation",
        "capabilityId": "Test.Consumer.GetSummary",
        "dependsOnCapabilityId": "MM.Inventory.GetAvailability",
    })
    sources = SemanticSourceDocuments(
        capabilities=caps,
        executor_bindings=base.executor_bindings,
        fact_types=facts,
        relations=relations,
    )
    snapshot = build_registry_snapshot(sources)
    return sources, snapshot


def test_compile_plan_v2_authors_dependency_edge_from_depends_on_relation():
    sources, snapshot = _sources_with_depends_on()
    handoff = EscalationHandoff(
        reason="depends-on",
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
        utterance="summary depending on inventory",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    dep_edges = [e for e in result.plan_graph["edges"] if e["kind"] == "dependency"]
    assert len(dep_edges) == 1
    inv = next(n for n in result.plan_graph["nodes"] if n["capabilityId"] == "MM.Inventory.GetAvailability")
    con = next(n for n in result.plan_graph["nodes"] if n["capabilityId"] == "Test.Consumer.GetSummary")
    assert dep_edges[0]["fromNodeId"] == inv["nodeId"]
    assert dep_edges[0]["toNodeId"] == con["nodeId"]
    # topologicalOrder: inv (prerequisite) before con (dependent)
    order = result.plan_graph["topologicalOrder"]
    assert order.index(inv["nodeId"]) < order.index(con["nodeId"])
    # v2 validator must accept the dependency edge
    assert not any(
        f.kind == "invalid_plan_graph" for f in result.governance_flags
    )


def test_compile_plan_v2_consumes_derived_relations_without_a_compiler_change():
    """T2 task 3.3.1 — the derived edge is rendered in the shape the third pass
    already reads, so honouring a *derived* dependency needs no compiler change.

    Not asserted by comparing key names against the compiler's source, but by
    running the compiler over derived relations and checking it authored the
    dependency edge. `plan_compiler_v2.py` is untouched by task 3.3.

    The direction is cross-checked against the `data` edge the compiler
    computed independently from `satisfiableByFactType`: if the derived
    dependsOn had consumer and producer the wrong way round, the two edges
    would disagree and the plan would order the producer after its consumer.
    """
    from sap_nexus_agent.semantic_planning.derivation import derive_data_dependencies

    sources, _ = _sources_with_derivable_identifier()
    view = derive_data_dependencies(sources)
    assert len(view.edges) == 1, (
        "the fixture must derive exactly one edge, otherwise this test proves "
        "nothing about what the compiler consumed"
    )
    relations = _unfreeze(sources.relations)
    assert not [
        r for r in relations["relations"] if r.get("relationType") == "dependsOn"
    ], "the real catalog already carries a dependsOn — the count below would be vacuous"
    relations["relations"].extend(view.to_relations())
    sources = SemanticSourceDocuments(
        capabilities=sources.capabilities,
        executor_bindings=sources.executor_bindings,
        fact_types=sources.fact_types,
        relations=relations,
    )
    snapshot = build_registry_snapshot(sources)
    result = compile_plan_v2(_quantity_handoff(snapshot, {}), snapshot, sources)

    dep_edges = [e for e in result.plan_graph["edges"] if e["kind"] == "dependency"]
    data_edges = [e for e in result.plan_graph["edges"] if e["kind"] == "data"]
    assert len(dep_edges) == 1
    assert len(data_edges) == 1
    assert dep_edges[0]["fromNodeId"] == data_edges[0]["fromNodeId"]
    assert dep_edges[0]["toNodeId"] == data_edges[0]["toNodeId"]
    producer = next(
        n
        for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "MM.Inventory.GetAvailability"
    )
    consumer = next(
        n
        for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "Test.Consumer.UseQuantity"
    )
    assert dep_edges[0]["fromNodeId"] == producer["nodeId"]
    assert dep_edges[0]["toNodeId"] == consumer["nodeId"]
    order = result.plan_graph["topologicalOrder"]
    assert order.index(producer["nodeId"]) < order.index(consumer["nodeId"])
    assert not any(f.kind == "invalid_plan_graph" for f in result.governance_flags)


def _sources_with_two_producers_of_one_fact_type(
    clone_first: bool = False,
) -> tuple[SemanticSourceDocuments, RegistrySnapshot]:
    """Two active producers of ``sapnexus:InventoryAvailabilityFact``.

    Built by cloning the real ``MM.Inventory.GetAvailability`` under a second id
    rather than inventing a producer: the point is that both candidates are
    equally legitimate, which is exactly what makes picking by list order wrong.

    ``clone_first`` places the clone *before* the original in the document, which
    is the only difference between the two fixtures the order-independence test
    below compares.
    """
    base = _real_sources()
    caps = _unfreeze(base.capabilities)
    original = next(
        c
        for c in caps["capabilities"]
        if c["capabilityId"] == "MM.Inventory.GetAvailability"
    )
    clone = _unfreeze(original)
    clone["capabilityId"] = "Test.Inventory.GetAvailabilityAlternate"
    clone["name"] = "Test Alternate Availability"
    clone["ontologyIri"] = "sapnexus:Test_Inventory_GetAvailabilityAlternate"
    if clone_first:
        caps["capabilities"].insert(0, clone)
    else:
        caps["capabilities"].append(clone)
    sources = SemanticSourceDocuments(
        capabilities=caps,
        executor_bindings=base.executor_bindings,
        fact_types=_unfreeze(base.fact_types),
        relations=base.relations,
    )
    return sources, build_registry_snapshot(sources)


def test_two_producers_of_one_fact_type_are_a_gap_not_a_list_index():
    """T2 task 3.4.4 — figure (b), "producers[0] silently-picks-one".

    Before this fix ``_build_plan_graph_v2`` authored ``producers[0]``, so the
    plan named one of two equally valid SAP calls by declaration order and said
    nothing about it. Latent while every Fact Type has one producer; load-bearing
    once the planner auto-pulls producers in (task 5.4).

    Both halves are asserted together on purpose. Refusing to author the node
    without recording the gap would be worse than the defect: ``_compute_gaps``
    derives ``missing_capability`` from *cards*, not nodes, so an ambiguous Fact
    Type has producers and would raise no gap at all — a plan quietly missing a
    node.
    """
    sources, snapshot = _sources_with_two_producers_of_one_fact_type()
    result = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)

    authored = {node["capabilityId"] for node in result.plan_graph["nodes"]}
    assert "MM.Inventory.GetAvailability" not in authored
    assert "Test.Inventory.GetAvailabilityAlternate" not in authored

    ambiguous = [g for g in result.gaps if g.kind == "ambiguous_producer"]
    assert len(ambiguous) == 1, result.gaps
    detail = ambiguous[0].detail
    assert "sapnexus:InventoryAvailabilityFact" in detail
    # Both candidates named. Naming one would be the silent pick, relocated.
    assert "MM.Inventory.GetAvailability" in detail
    assert "Test.Inventory.GetAvailabilityAlternate" in detail


def test_the_ambiguous_producer_gap_is_independent_of_declaration_order():
    """The detail string is what a human reads to disambiguate, so its candidate
    order must not come from the document's.

    Compared across two *different* fixtures rather than two runs of one: running
    the same input twice cannot distinguish "sorted" from "stably wrong", which
    is how the first version of this test passed a mutation it should have
    caught. The ordering authority is
    ``_index_producers_by_fact_type``; remove its sort and this fails.
    """
    appended, appended_snapshot = _sources_with_two_producers_of_one_fact_type()
    inserted, inserted_snapshot = _sources_with_two_producers_of_one_fact_type(
        clone_first=True
    )
    first = compile_plan_v2(
        _dual_read_handoff(appended_snapshot), appended_snapshot, appended
    )
    second = compile_plan_v2(
        _dual_read_handoff(inserted_snapshot), inserted_snapshot, inserted
    )
    details = [g.detail for g in first.gaps if g.kind == "ambiguous_producer"]
    assert details, "no ambiguity gap — the comparison below would be vacuous"
    assert details == [
        g.detail for g in second.gaps if g.kind == "ambiguous_producer"
    ]
    # And it is the alphabetical order, not merely a stable one.
    assert details[0].index("MM.Inventory.GetAvailability") < details[0].index(
        "Test.Inventory.GetAvailabilityAlternate"
    )


def test_one_producer_per_fact_type_records_no_ambiguity_gap():
    """The shipped registry. An `ambiguous_producer` gap that fired here would
    block every plan at the composition boundary."""
    snapshot = _real_snapshot()
    result = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, _real_sources())
    assert [g for g in result.gaps if g.kind == "ambiguous_producer"] == []
    assert result.plan_graph["nodes"], "no nodes — the assertion above is vacuous"


def test_compile_plan_v2_topological_order_no_edges_falls_back_to_node_id_order():
    """No edges -> topologicalOrder falls back to nodeId sorted order (deterministic)."""
    snapshot = _real_snapshot()
    sources = _real_sources()
    result = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)
    order = result.plan_graph["topologicalOrder"]
    # Dual-read: two READ nodes, no data/dependency edges between them.
    # Fallback: nodeId sorted order.
    assert order == sorted(order)


def test_compile_plan_v2_topological_order_respects_data_edge():
    """Data edge (producer -> consumer) must be respected in topologicalOrder.

    The handoff deliberately lists the CONSUMER first to verify the topo
    sort reorders based on the data edge, not insertion order.
    """
    sources, snapshot = _sources_with_fact_field()
    handoff = EscalationHandoff(
        reason="fact-field",
        matched_intents=[
            MatchedIntent(
                capability_id="Test.Consumer.GetSummary",
                parameters={},
                missing=[],
            ),
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "M1", "plant": "5300"},
                missing=[],
            ),
        ],
        utterance="summary from inventory",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    order = result.plan_graph["topologicalOrder"]
    inv = next(n for n in result.plan_graph["nodes"] if n["capabilityId"] == "MM.Inventory.GetAvailability")
    con = next(n for n in result.plan_graph["nodes"] if n["capabilityId"] == "Test.Consumer.GetSummary")
    # Producer (inv) must come before consumer (con) due to data edge,
    # even though consumer was listed first in the handoff (insertion order).
    assert order.index(inv["nodeId"]) < order.index(con["nodeId"])


# ---- Task 10: partition authoring - write Action node isolation ----


def test_compile_plan_v2_partitions_write_action_into_action_partition():
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="write",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.PR.CreateDraft",
                parameters={
                    "material": "M1", "plant": "5100", "quantity": 10,
                    "unit": "EA", "delivery_date": "2026-08-01",
                    "purchasing_group": "PG1",
                },
                missing=[],
            )
        ],
        utterance="create PR",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    pr_nodes = [n for n in result.plan_graph["nodes"] if n["capabilityId"] == "MM.PR.CreateDraft"]
    assert pr_nodes
    assert pr_nodes[0]["nodeId"] in result.plan_graph["actionPartition"]
    assert pr_nodes[0]["nodeId"] not in result.plan_graph["readPartition"]
    assert pr_nodes[0]["governance"]["requiresApproval"] is True
    assert pr_nodes[0]["governance"]["capabilityKind"] == "Action"


# ---- Task 11: snapshot drift -> PlannerFailure(SNAPSHOT_DRIFT) ----


def test_compile_plan_v2_raises_planner_failure_on_snapshot_drift():
    snapshot = _real_snapshot()
    sources = _real_sources()
    drift_handoff = EscalationHandoff(
        reason="drift",
        matched_intents=[
            MatchedIntent("MM.Inventory.GetAvailability", {"material": "M1", "plant": "5300"}, [])
        ],
        utterance="drift",
        registry_snapshot_id="sha256:" + "f" * 64,  # 不同于 snapshot.snapshot_id
    )
    with pytest.raises(PlannerFailure) as exc_info:
        compile_plan_v2(drift_handoff, snapshot, sources)
    assert exc_info.value.error_type == "SNAPSHOT_DRIFT"
    assert exc_info.value.snapshot_id == snapshot.snapshot_id
    assert "expected_snapshot_id" in exc_info.value.audit_evidence
    assert "actual_snapshot_id" in exc_info.value.audit_evidence


# ---- Task 12: handoff entrypoint + dry-run output + no Gateway/SAP ----

from unittest.mock import MagicMock

from sap_nexus_agent.gateway_client import GatewayClientProtocol


def test_compile_plan_v2_from_handoff_outputs_all_v2_fields_without_gateway(monkeypatch):
    import sap_nexus_agent.gateway_client as gateway_module

    exploding = MagicMock(side_effect=AssertionError(
        "GatewayClient must not be instantiated by v2 compiler"
    ))
    monkeypatch.setattr(gateway_module, "GatewayClient", exploding)
    mock_gateway = MagicMock(spec=GatewayClientProtocol)

    snapshot = _real_snapshot()
    sources = _real_sources()
    from sap_nexus_agent.planner.handoff import compile_plan_v2_from_handoff
    result = compile_plan_v2_from_handoff(_dual_read_handoff(snapshot), snapshot, sources)

    # v2 dry-run 输出齐全
    assert result.plan_graph["planGraphVersion"] == 2
    assert result.projection_ref == []
    assert result.rule_set_refs == []
    assert result.snapshot_id == snapshot.snapshot_id
    assert isinstance(result.gaps, list)
    assert isinstance(result.governance_flags, list)
    assert isinstance(result.rationale, str) and result.rationale
    # 不调 Gateway
    mock_gateway.validate.assert_not_called()
    mock_gateway.execute.assert_not_called()
    exploding.assert_not_called()


# ---- Task 13: 7 类 bad-case fail-closed (compiler layer) ----


def test_bad_case_unknown_capability_fails_closed():
    """spec R4: unknown capability -> UNKNOWN_CAPABILITY, plan invalid."""
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="bad",
        matched_intents=[MatchedIntent("MM.DoesNotExist.Get", {"material": "M1", "plant": "5300"}, [])],
        utterance="bad",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    assert result.plan_graph is not None  # 不返回 None
    assert any(f.kind == "invalid_plan_graph" for f in result.governance_flags)


def test_bad_case_missing_parameter_source_fails_closed():
    """spec R4: required parameter no source -> PARAMETER_SOURCE_MISSING."""
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="bad",
        matched_intents=[MatchedIntent("MM.Inventory.GetAvailability", {"plant": "5300"}, [])],
        utterance="bad",  # 缺 material
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    assert result.plan_graph is not None
    assert any(f.kind == "invalid_plan_graph" for f in result.governance_flags)
    # gap 记录 missing_parameter
    assert any(g.kind == "missing_parameter" for g in result.gaps)


def test_bad_case_snapshot_drift_fails_closed():
    """spec R7: snapshot drift -> PlannerFailure(SNAPSHOT_DRIFT)。"""
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="bad",
        matched_intents=[MatchedIntent("MM.Inventory.GetAvailability", {"material": "M1", "plant": "5300"}, [])],
        utterance="bad",
        registry_snapshot_id="sha256:" + "f" * 64,
    )
    with pytest.raises(PlannerFailure) as exc:
        compile_plan_v2(handoff, snapshot, sources)
    assert exc.value.error_type == "SNAPSHOT_DRIFT"


def test_invalid_plan_preserves_structured_issues_not_none():
    """spec R4: invalid plan must return structured issues (never None)."""
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = EscalationHandoff(
        reason="bad",
        matched_intents=[MatchedIntent("MM.Inventory.GetAvailability", {"plant": "5300"}, [])],
        utterance="bad",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    result = compile_plan_v2(handoff, snapshot, sources)
    assert result is not None
    assert result.plan_graph is not None
    invalid_flags = [f for f in result.governance_flags if f.kind == "invalid_plan_graph"]
    assert invalid_flags
    # rationale 携带 issue 摘要
    assert "issue" in result.rationale or "failed" in result.rationale


# ---- Task 14: dual-READ + factField fixture stability tests ----


def test_dual_read_fixture_is_stable_with_empty_edges_and_refs():
    snapshot = _real_snapshot()
    sources = _real_sources()
    handoff = _dual_read_handoff(snapshot)
    r1 = compile_plan_v2(handoff, snapshot, sources)
    r2 = compile_plan_v2(handoff, snapshot, sources)
    assert r1 == r2
    pg = r1.plan_graph
    assert pg["edges"] == []
    assert pg["projectionRef"] == []
    assert pg["ruleSetRefs"] == []
    assert pg["actionPartition"] == []
    assert set(pg["readPartition"]) == {n["nodeId"] for n in pg["nodes"]}
    # snapshotId 绑定
    assert pg["snapshotId"] == snapshot.snapshot_id
    # goalOutputs 覆盖两个 FactType
    output_facts = {o["factTypeId"] for o in pg["goalOutputs"]}
    assert "sapnexus:InventoryAvailabilityFact" in output_facts
    assert "sapnexus:PurchaseOrderSupplyFact" in output_facts


def test_fact_field_fixture_produces_data_edge_and_stable():
    sources, snapshot = _sources_with_fact_field()
    handoff = EscalationHandoff(
        reason="fact-field",
        matched_intents=[
            MatchedIntent("MM.Inventory.GetAvailability", {"material": "M1", "plant": "5300"}, []),
            MatchedIntent("Test.Consumer.GetSummary", {}, []),
        ],
        utterance="summary",
        registry_snapshot_id=snapshot.snapshot_id,
    )
    r1 = compile_plan_v2(handoff, snapshot, sources)
    r2 = compile_plan_v2(handoff, snapshot, sources)
    assert r1 == r2
    data_edges = [e for e in r1.plan_graph["edges"] if e["kind"] == "data"]
    assert len(data_edges) == 1


# ---- Task 15: dry-run output surface + v1 regression guard ----


def test_v2_dry_run_output_surfaces_all_fields():
    snapshot = _real_snapshot()
    sources = _real_sources()
    result = compile_plan_v2(_dual_read_handoff(snapshot), snapshot, sources)
    # plan
    assert result.plan_graph["planGraphVersion"] == 2
    # gaps
    assert isinstance(result.gaps, list)
    # governance
    assert isinstance(result.governance_flags, list)
    # projectionRef / ruleSetRefs
    assert result.projection_ref == []
    assert result.rule_set_refs == []
    # snapshotId
    assert result.snapshot_id == snapshot.snapshot_id
    # rationale 含节点数
    assert str(len(result.plan_graph["nodes"])) in result.rationale


def test_v1_compiler_still_produces_v1_plan_graph():
    """spec R1: v1 compiler 输出 planGraphVersion:1，不受 v2 影响。"""
    from sap_nexus_agent.planner.plan_compiler import compile_dry_run
    from sap_nexus_agent.planner.goal_spec import GoalSpec, GoalConstraint
    goal = GoalSpec(
        goal_id="goal.regression",
        goal_type="sapnexus:PlannerDryRunGoal",
        desired_fact_types=("sapnexus:InventoryAvailabilityFact",),
        execution_mode="PLAN_ONLY",
        constraints=(
            GoalConstraint("material", "sapnexus:MaterialNumber", "M1"),
            GoalConstraint("plant", "sapnexus:Plant", "5300"),
        ),
    )
    result = compile_dry_run(goal, _real_snapshot(), _real_sources())
    assert result.plan_graph["planGraphVersion"] == 1
    # v1 不含 v2 字段
    for field in ("readPartition", "actionPartition", "projectionRef", "ruleSetRefs"):
        assert field not in result.plan_graph
