"""The deterministic data dependency deriver (T2: task 3.1).

Requirement: openspec/changes/derived-parameter-binding/specs/
registry-ontology-contract/spec.md — producer→consumer data dependency edges
SHALL be *derived* by matching Fact Type fields against capability signatures.

**Invariant 3 lives in this module.** An edge that a reader cannot recompute
from the registry is not governance, it is a hand-written claim. So the
acceptance criterion for `ontology/capability-relations.yaml` is never "the file
is non-empty" — it is "the derived view is non-empty", and this file is where
that view's correctness is pinned.

**Invariant 2 lives here too.** The deriver authors, it never executes. Task
3.1.4 asserts that by source inspection rather than by trust: the module's
import set must be a subset of an allowlist, so any future import that could
reach the Gateway, SAP, or the network fails this test closed.

Candidate scoping, in the order the deriver applies it:

1. The consuming input declares `satisfiableByFactType: F`.
2. `F`'s declared fields are searched for one whose `semanticType` equals the
   input's. The scoping to `F` is load-bearing, not decorative — a field of the
   same semantic type in a *different* Fact Type is not a candidate.
3. The candidate producers are the **active** capabilities publishing an output
   with `factTypeRef == F` and the same `semanticType`.

`required` is deliberately not part of the scoping. The deriver reports what
*can* be derived; whether the planner pulls it in is an authoring policy that
lives in `plan_compiler_v2`, not a property of the registry.

Cases that are neither an edge nor an error — zero matches, more than one
match, or a `cardinality: many` field — are skipped here and become explicit
diagnostics in task 3.4. They are asserted as skips below so the interim
behaviour is pinned rather than assumed.
"""

from __future__ import annotations

import ast
from pathlib import Path

from sap_nexus_agent.semantic_planning import SemanticSourceDocuments
from sap_nexus_agent.semantic_planning.derivation import (
    DerivedDataEdge,
    derive_data_dependencies,
)

DERIVATION_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "sap_nexus_agent"
    / "semantic_planning"
    / "derivation.py"
)

WIDGET_FACT = {
    "factTypeId": "test:WidgetFact",
    "name": "Widget Fact",
    "description": "Fabricated Fact Type; never registered.",
    "businessObject": "Widget",
    "predicate": "test:hasWidget",
    "semanticType": "test:Widget",
    "keyedBy": ["test:WidgetNumber"],
    "fields": [
        {
            "name": "widgetUnit",
            "semanticType": "test:WidgetUnit",
            "cardinality": "one",
            "optional": False,
            "description": "Base unit of the widget.",
        }
    ],
}

WIDGET_PRODUCER = {
    "capabilityId": "T.Widget.GetInfo",
    "status": "active",
    "kind": "Function",
    "inputs": [
        {
            "name": "widget",
            "semanticType": "test:WidgetNumber",
            "bindingKind": "identifier",
            "required": True,
        }
    ],
    "outputs": [
        {
            "name": "widgetUnit",
            "semanticType": "test:WidgetUnit",
            "evidenceRole": "primaryFact",
            "factTypeRef": "test:WidgetFact",
        }
    ],
}

WIDGET_CONSUMER = {
    "capabilityId": "T.Widget.Order",
    "status": "active",
    "kind": "Action",
    "inputs": [
        {
            "name": "unit",
            "semanticType": "test:WidgetUnit",
            "bindingKind": "identifier",
            "satisfiableByFactType": "test:WidgetFact",
            "required": True,
        }
    ],
    "outputs": [],
}

EXPECTED_EDGE = DerivedDataEdge(
    consumer_capability_id="T.Widget.Order",
    consumer_input_name="unit",
    producer_capability_id="T.Widget.GetInfo",
    producer_output_name="widgetUnit",
    fact_type_id="test:WidgetFact",
    fact_field_name="widgetUnit",
    semantic_type="test:WidgetUnit",
)


def _documents(capabilities: list[dict], fact_types: list[dict]):
    return SemanticSourceDocuments(
        capabilities={"version": 2, "capabilities": capabilities},
        executor_bindings={"version": 1, "executorBindings": []},
        fact_types={"version": 3, "factTypes": fact_types},
        relations={"version": 1, "relations": []},
    )


def _copy(value):
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def _widget_documents():
    return _documents(
        [_copy(WIDGET_PRODUCER), _copy(WIDGET_CONSUMER)], [_copy(WIDGET_FACT)]
    )


# ---- 3.1.1: determinism ----


def test_derivation_is_byte_identical_across_runs():
    """3.1.1 — same documents in, same bytes out, ordering included.

    Compared through `to_dict()` as well as the tuple, because the `runtime/`
    artifact at task 3.5 serialises that dict: a set leaking into the ordering
    would show up there, not in the dataclass equality.
    """
    documents = _widget_documents()
    first = derive_data_dependencies(documents)
    second = derive_data_dependencies(_widget_documents())
    assert first.edges == second.edges
    assert first.to_dict() == second.to_dict()


def test_derivation_orders_edges_independently_of_declaration_order():
    """Declaration order must not survive into the derived view.

    Two consumers, so the assertion has something to order. With a single edge
    the comparison would hold no matter how the deriver sorted.
    """
    second_consumer = _copy(WIDGET_CONSUMER)
    second_consumer["capabilityId"] = "T.Widget.Reserve"
    fact_types = [_copy(WIDGET_FACT)]
    forward = derive_data_dependencies(
        _documents(
            [_copy(WIDGET_PRODUCER), _copy(WIDGET_CONSUMER), second_consumer],
            fact_types,
        )
    )
    reversed_order = derive_data_dependencies(
        _documents(
            [_copy(second_consumer), _copy(WIDGET_CONSUMER), _copy(WIDGET_PRODUCER)],
            fact_types,
        )
    )
    assert len(forward.edges) == 2
    assert forward.edges == reversed_order.edges
    assert forward.edges == tuple(sorted(forward.edges))


# ---- 3.1.2: the derivation itself ----


def test_a_declared_field_and_an_active_producer_yield_one_edge():
    view = derive_data_dependencies(_widget_documents())
    assert view.edges == (EXPECTED_EDGE,)


def test_the_edge_records_both_the_fact_field_and_the_producer_output():
    """Provenance, not redundancy.

    Under the C5 publication rule these two names are equal today, but they are
    facts about different layers: the runtime reads `fact_field_name` off the
    projected Fact, while `producer_output_name` is what the Gateway returned.
    Collapsing them would erase which layer an edge was derived from.
    """
    edge = derive_data_dependencies(_widget_documents()).edges[0]
    assert edge.fact_field_name == "widgetUnit"
    assert edge.producer_output_name == "widgetUnit"
    assert edge.fact_type_id == "test:WidgetFact"
    assert edge.semantic_type == "test:WidgetUnit"


def test_an_input_without_satisfiable_by_fact_type_derives_nothing():
    consumer = _copy(WIDGET_CONSUMER)
    del consumer["inputs"][0]["satisfiableByFactType"]
    documents = _documents([_copy(WIDGET_PRODUCER), consumer], [_copy(WIDGET_FACT)])
    assert derive_data_dependencies(documents).edges == ()


def test_a_deprecated_producer_is_not_a_candidate():
    producer = _copy(WIDGET_PRODUCER)
    producer["status"] = "deprecated"
    documents = _documents(
        [producer, _copy(WIDGET_CONSUMER)], [_copy(WIDGET_FACT)]
    )
    assert derive_data_dependencies(documents).edges == ()


def test_a_capability_never_derives_a_parameter_from_itself():
    """A self-edge would be a cycle the plan executor cannot order."""
    both = _copy(WIDGET_PRODUCER)
    both["inputs"].append(_copy(WIDGET_CONSUMER)["inputs"][0])
    documents = _documents([both], [_copy(WIDGET_FACT)])
    assert derive_data_dependencies(documents).edges == ()


def test_the_real_registry_derives_no_edges_yet():
    """3.7's expectation, pinned as a unit fact.

    No input in `registry/capabilities.yaml` declares `satisfiableByFactType`
    yet — `MM.Material.GetInfo` (task 5.2) is the first consumer. An empty view
    here is the correct result, and it is only meaningful because the fabricated
    pair above proves the deriver can produce a non-empty one.
    """
    from sap_nexus_agent.semantic_planning import load_semantic_sources

    repo_root = Path(__file__).resolve().parents[2]
    assert derive_data_dependencies(load_semantic_sources(repo_root)).edges == ()


# ---- 3.1.3: the satisfiableByFactType scoping is load-bearing ----


def test_a_matching_field_in_another_fact_type_is_not_a_candidate():
    """3.1.3, first guard — the declared Fact Type bounds the *field* search.

    Isolated deliberately. An earlier version of this test also moved the
    producer into `test:GadgetFact`, which made it pass even with the field
    scoping removed — the producer scoping was doing the work and the assertion
    proved nothing. Here the producer publishes into `test:WidgetFact`
    correctly, so only the field scoping can reject the edge: `test:WidgetFact`
    declares no field of this semantic type, `test:GadgetFact` does.
    """
    widget_fact_without_the_field = _copy(WIDGET_FACT)
    widget_fact_without_the_field["fields"] = []
    gadget_fact = _copy(WIDGET_FACT)
    gadget_fact["factTypeId"] = "test:GadgetFact"

    documents = _documents(
        [_copy(WIDGET_PRODUCER), _copy(WIDGET_CONSUMER)],
        [widget_fact_without_the_field, gadget_fact],
    )
    assert derive_data_dependencies(documents).edges == ()


def test_a_producer_publishing_into_another_fact_type_is_not_a_candidate():
    """3.1.3, second guard — the declared Fact Type bounds the *producer* set.

    The field is declared where the consumer says it is; only the producer is
    wrong. Publishing the same semantic type under a different `factTypeRef` is
    a different fact about a different subject, not a substitute.
    """
    gadget_fact = _copy(WIDGET_FACT)
    gadget_fact["factTypeId"] = "test:GadgetFact"
    gadget_producer = _copy(WIDGET_PRODUCER)
    gadget_producer["outputs"][0]["factTypeRef"] = "test:GadgetFact"

    documents = _documents(
        [gadget_producer, _copy(WIDGET_CONSUMER)],
        [_copy(WIDGET_FACT), gadget_fact],
    )
    assert derive_data_dependencies(documents).edges == ()


def test_an_unknown_declared_fact_type_derives_nothing_and_does_not_raise():
    """`UNKNOWN_FACT_TYPE` is the validator's diagnostic, not the deriver's.

    The deriver must stay usable on documents the validator has already
    rejected, so it skips rather than raising.
    """
    consumer = _copy(WIDGET_CONSUMER)
    consumer["inputs"][0]["satisfiableByFactType"] = "test:NoSuchFact"
    documents = _documents([_copy(WIDGET_PRODUCER), consumer], [_copy(WIDGET_FACT)])
    assert derive_data_dependencies(documents).edges == ()


# ---- skips that task 3.4 turns into diagnostics ----


def test_a_cardinality_many_field_is_skipped_pending_reduction():
    """A list cannot bind a scalar parameter without an operator, and the
    deriver never selects one. Task 3.4 makes this a `needsReduction`
    diagnostic; until then it must be a skip, not a silently wrong edge."""
    fact = _copy(WIDGET_FACT)
    fact["fields"][0]["cardinality"] = "many"
    documents = _documents(
        [_copy(WIDGET_PRODUCER), _copy(WIDGET_CONSUMER)], [fact]
    )
    assert derive_data_dependencies(documents).edges == ()


def test_two_matching_fields_are_skipped_rather_than_resolved():
    """Task 3.4's `ambiguous`, trigger (i). The deriver reports; it never
    resolves by declaration order."""
    fact = _copy(WIDGET_FACT)
    second = _copy(fact["fields"][0])
    second["name"] = "widgetUnitAlternate"
    fact["fields"].append(second)
    documents = _documents(
        [_copy(WIDGET_PRODUCER), _copy(WIDGET_CONSUMER)], [fact]
    )
    assert derive_data_dependencies(documents).edges == ()


def test_two_active_producers_are_skipped_rather_than_resolved():
    """Task 3.4's `ambiguous`, trigger (ii) — and the shape that makes
    `plan_compiler_v2`'s `producers[0]` a defect rather than a latency."""
    second_producer = _copy(WIDGET_PRODUCER)
    second_producer["capabilityId"] = "T.Widget.GetInfoAlternate"
    documents = _documents(
        [_copy(WIDGET_PRODUCER), second_producer, _copy(WIDGET_CONSUMER)],
        [_copy(WIDGET_FACT)],
    )
    assert derive_data_dependencies(documents).edges == ()


def test_a_field_no_active_producer_publishes_is_skipped():
    producer = _copy(WIDGET_PRODUCER)
    producer["outputs"][0]["semanticType"] = "test:SomethingElse"
    documents = _documents(
        [producer, _copy(WIDGET_CONSUMER)], [_copy(WIDGET_FACT)]
    )
    assert derive_data_dependencies(documents).edges == ()


# ---- 3.1.4: invariant 2, asserted by source inspection ----

ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "dataclasses",
        "typing",
        ".contracts",
    }
)


def _imported_modules() -> set[str]:
    tree = ast.parse(DERIVATION_SOURCE.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add("." * node.level + (node.module or ""))
    assert modules, "failed to parse imports — the invariant-2 lock would be vacuous"
    return modules


def test_derivation_imports_nothing_that_can_reach_the_gateway_or_sap():
    """3.1.4 — invariant 2: the intent layer authors, it never executes.

    Asserted as `imports ⊆ allowlist`, not as `forbidden names absent`. A
    denylist only catches the I/O libraries someone thought of; this fails
    closed on any import at all, including one added years from now.
    """
    unexpected = _imported_modules() - ALLOWED_IMPORTS
    assert not unexpected, (
        "derivation.py must not import anything outside the allowlist; "
        f"adding {sorted(unexpected)} requires proving it cannot perform I/O"
    )
