"""The deterministic data dependency deriver (T2: tasks 3.1 and 3.3).

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

The fabricated capability pair these tests vary comes from
`agent/tests/fixtures/semantic_planning/derivation-positive-control.yaml` via
`positive_control.py` — one authority, loaded fresh per call. Inlining a second
copy here would be the very field-list restatement task 2.7 just removed.
`test_derivation_positive_control.py` owns that fixture's own assertions,
including proof that it never reaches the execution boundary.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from positive_control import (
    positive_control_capability,
    positive_control_documents,
    positive_control_fact_type,
)
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

PRODUCER_ID = "T.Widget.GetInfo"
CONSUMER_ID = "T.Widget.Order"
WIDGET_FACT_ID = "test:WidgetFact"

EXPECTED_EDGE = DerivedDataEdge(
    consumer_capability_id=CONSUMER_ID,
    consumer_input_name="unit",
    producer_capability_id=PRODUCER_ID,
    producer_output_name="widgetUnit",
    fact_type_id=WIDGET_FACT_ID,
    fact_field_name="widgetUnit",
    semantic_type="test:WidgetUnit",
)


def _producer() -> dict:
    return positive_control_capability(PRODUCER_ID)


def _consumer() -> dict:
    return positive_control_capability(CONSUMER_ID)


def _widget_fact() -> dict:
    return positive_control_fact_type(WIDGET_FACT_ID)


def _documents(capabilities: list[dict], fact_types: list[dict]):
    return positive_control_documents(
        capabilities=capabilities, fact_types=fact_types
    )


def _widget_documents():
    return positive_control_documents()


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
    second_consumer = _consumer()
    second_consumer["capabilityId"] = "T.Widget.Reserve"
    fact_types = [_widget_fact()]
    forward = derive_data_dependencies(
        _documents([_producer(), _consumer(), second_consumer], fact_types)
    )
    reversed_order = derive_data_dependencies(
        _documents([second_consumer, _consumer(), _producer()], fact_types)
    )
    assert len(forward.edges) == 2
    assert forward.edges == reversed_order.edges
    assert forward.edges == tuple(sorted(forward.edges))


# ---- 3.1.2: the derivation itself ----


def test_a_declared_field_and_an_active_producer_yield_one_edge():
    """The positive control's headline assertion (3.2.2).

    Exactly one edge, out of two `satisfiableByFactType` inputs the consumer
    declares — `tags` is excluded by cardinality alone, so "one" is a real
    constraint here rather than an artefact of the fixture's size.
    """
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
    assert edge.fact_type_id == WIDGET_FACT_ID
    assert edge.semantic_type == "test:WidgetUnit"


def test_an_input_without_satisfiable_by_fact_type_derives_nothing():
    consumer = _consumer()
    for input_field in consumer["inputs"]:
        del input_field["satisfiableByFactType"]
    documents = _documents([_producer(), consumer], [_widget_fact()])
    assert derive_data_dependencies(documents).edges == ()


def test_a_deprecated_producer_is_not_a_candidate():
    producer = _producer()
    producer["status"] = "deprecated"
    documents = _documents([producer, _consumer()], [_widget_fact()])
    assert derive_data_dependencies(documents).edges == ()


def test_a_capability_never_derives_a_parameter_from_itself():
    """A self-edge would be a cycle the plan executor cannot order."""
    both = _producer()
    both["inputs"].extend(_consumer()["inputs"])
    documents = _documents([both], [_widget_fact()])
    assert derive_data_dependencies(documents).edges == ()


def test_the_real_registry_derives_no_edges_yet():
    """3.7's expectation, pinned as a unit fact.

    No input in `registry/capabilities.yaml` declares `satisfiableByFactType`
    yet — `MM.Material.GetInfo` (task 5.2) is the first consumer. An empty view
    here is the correct result, and it is only meaningful because the positive
    control above proves the deriver can produce a non-empty one.
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
    widget_fact_without_the_field = _widget_fact()
    widget_fact_without_the_field["fields"] = []
    gadget_fact = _widget_fact()
    gadget_fact["factTypeId"] = "test:GadgetFact"

    documents = _documents(
        [_producer(), _consumer()],
        [widget_fact_without_the_field, gadget_fact],
    )
    assert derive_data_dependencies(documents).edges == ()


def test_a_producer_publishing_into_another_fact_type_is_not_a_candidate():
    """3.1.3, second guard — the declared Fact Type bounds the *producer* set.

    The field is declared where the consumer says it is; only the producer is
    wrong. Publishing the same semantic type under a different `factTypeRef` is
    a different fact about a different subject, not a substitute.
    """
    gadget_fact = _widget_fact()
    gadget_fact["factTypeId"] = "test:GadgetFact"
    gadget_producer = _producer()
    for output in gadget_producer["outputs"]:
        output["factTypeRef"] = "test:GadgetFact"

    documents = _documents(
        [gadget_producer, _consumer()], [_widget_fact(), gadget_fact]
    )
    assert derive_data_dependencies(documents).edges == ()


def test_an_unknown_declared_fact_type_derives_nothing_and_does_not_raise():
    """`UNKNOWN_FACT_TYPE` is the validator's diagnostic, not the deriver's.

    The deriver must stay usable on documents the validator has already
    rejected, so it skips rather than raising.
    """
    consumer = _consumer()
    for input_field in consumer["inputs"]:
        input_field["satisfiableByFactType"] = "test:NoSuchFact"
    documents = _documents([_producer(), consumer], [_widget_fact()])
    assert derive_data_dependencies(documents).edges == ()


# ---- skips that task 3.4 turns into diagnostics ----


def test_the_cardinality_many_field_is_skipped_pending_reduction():
    """A list cannot bind a scalar parameter without an operator, and the
    deriver never selects one. Task 3.4 makes this a `needsReduction`
    diagnostic; until then it must be a skip, not a silently wrong edge."""
    view = derive_data_dependencies(_widget_documents())
    assert "tags" not in {edge.consumer_input_name for edge in view.edges}


def test_cardinality_is_the_only_thing_blocking_the_many_field():
    """The companion to the test above, and the reason it means anything.

    Flip `widgetTags` to `cardinality: one` and the edge appears. So the field
    is declared, the producer publishes it, the consumer wants it, and the
    exclusion is cardinality — not a missing declaration somewhere.
    """
    fact = _widget_fact()
    next(f for f in fact["fields"] if f["name"] == "widgetTags")["cardinality"] = "one"
    view = derive_data_dependencies(_documents([_producer(), _consumer()], [fact]))
    assert "tags" in {edge.consumer_input_name for edge in view.edges}


def test_two_matching_fields_are_skipped_rather_than_resolved():
    """Task 3.4's `ambiguous`, trigger (i). The deriver reports; it never
    resolves by declaration order."""
    fact = _widget_fact()
    alternate = dict(next(f for f in fact["fields"] if f["name"] == "widgetUnit"))
    alternate["name"] = "widgetUnitAlternate"
    fact["fields"].append(alternate)
    documents = _documents([_producer(), _consumer()], [fact])
    assert derive_data_dependencies(documents).edges == ()


def test_two_active_producers_are_skipped_rather_than_resolved():
    """Task 3.4's `ambiguous`, trigger (ii) — and the shape that makes
    `plan_compiler_v2`'s `producers[0]` a defect rather than a latency."""
    second_producer = _producer()
    second_producer["capabilityId"] = "T.Widget.GetInfoAlternate"
    documents = _documents(
        [_producer(), second_producer, _consumer()], [_widget_fact()]
    )
    assert derive_data_dependencies(documents).edges == ()


def test_a_field_no_active_producer_publishes_is_skipped():
    producer = _producer()
    for output in producer["outputs"]:
        output["semanticType"] = "test:SomethingElse"
    documents = _documents([producer, _consumer()], [_widget_fact()])
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


# ---- 3.3: rendering into the catalog's dependsOn shape ----

RELATION_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "schemas"
    / "capability-relation.schema.json"
)


def _relation_type_vocabulary() -> set[str]:
    """The relation kinds the catalog schema admits, read from the schema.

    Read rather than restated: a test carrying its own copy of the vocabulary
    would still pass after someone added a third kind to the schema, which is
    precisely the change 3.3.2 exists to catch.
    """
    schema = json.loads(RELATION_SCHEMA.read_text(encoding="utf-8"))
    refs = schema["$defs"]["relation"]["oneOf"]
    names = {ref["$ref"].rsplit("/", 1)[-1] for ref in refs}
    vocabulary = {
        schema["$defs"][name]["properties"]["relationType"]["const"]
        for name in names
    }
    assert vocabulary, "failed to read the schema — the 3.3.2 lock would be vacuous"
    return vocabulary


def test_a_derived_edge_renders_in_the_catalog_depends_on_shape():
    """3.3.1 — the rendered relation is the shape the catalog already defines.

    Key set asserted by equality against the schema's own required set plus
    `origin`, so a renamed or extra key fails here rather than silently at the
    compiler, whose third pass reads these names by `.get()` and skips what it
    does not recognise.
    """
    relation = EXPECTED_EDGE.to_relation()
    required = set(
        json.loads(RELATION_SCHEMA.read_text(encoding="utf-8"))["$defs"][
            "dependsOn"
        ]["required"]
    )
    assert set(relation) == required | {"origin"}
    assert relation["capabilityId"] == CONSUMER_ID
    assert relation["dependsOnCapabilityId"] == PRODUCER_ID
    assert relation["origin"] == "derived"


def test_derivedness_is_a_field_not_a_new_relation_type():
    """3.3.2 — ruling ①: the relation catalog stays additive, two kinds only.

    A `derivedDependsOn` kind would have been the easy way to mark provenance,
    and it would have forced every existing reader — schema, validator,
    compiler third pass — to learn a name. `origin` costs readers nothing.
    """
    vocabulary = _relation_type_vocabulary()
    assert vocabulary == {"dependsOn", "precondition"}
    fact = _widget_fact()
    next(f for f in fact["fields"] if f["name"] == "widgetTags")["cardinality"] = "one"
    second_consumer = _consumer()
    second_consumer["capabilityId"] = "T.Widget.Reserve"
    view = derive_data_dependencies(
        _documents([_producer(), _consumer(), second_consumer], [fact])
    )
    rendered = view.to_relations()
    assert rendered, "nothing rendered — the assertion below would be vacuous"
    assert {relation["relationType"] for relation in rendered} == {"dependsOn"}
    assert {relation["origin"] for relation in rendered} == {"derived"}


def test_two_derived_parameters_from_one_producer_are_one_relation():
    """A dependsOn relation is capability-level, not parameter-level.

    Two derived parameters flowing from the same producer are one dependency.
    Rendering both would make the compiler author two identical `dependency`
    edges, and the S1 validator expects exactly one per dependsOn.
    """
    fact = _widget_fact()
    next(f for f in fact["fields"] if f["name"] == "widgetTags")["cardinality"] = "one"
    view = derive_data_dependencies(_documents([_producer(), _consumer()], [fact]))
    assert len(view.edges) == 2
    assert len(view.to_relations()) == 1


def test_two_producer_consumer_pairs_render_two_relations():
    """The companion to the deduplication test: collapsing is per pair, not
    global. One relation for two pairs would be the same bug in the other
    direction."""
    second_consumer = _consumer()
    second_consumer["capabilityId"] = "T.Widget.Reserve"
    view = derive_data_dependencies(
        _documents([_producer(), _consumer(), second_consumer], [_widget_fact()])
    )
    rendered = view.to_relations()
    assert len(rendered) == 2
    assert len({relation["relationId"] for relation in rendered}) == 2
    assert {relation["capabilityId"] for relation in rendered} == {
        CONSUMER_ID,
        "T.Widget.Reserve",
    }


def test_the_relation_id_names_both_capabilities():
    """The id must be recomputable by a reader, not a lookup-table key.

    An opaque counter would make two runs over reordered documents produce
    different ids for the same relation, and a diff of the derived view would
    then be unreadable.
    """
    relation = EXPECTED_EDGE.to_relation()
    assert CONSUMER_ID in relation["relationId"]
    assert PRODUCER_ID in relation["relationId"]


def test_rendered_relations_are_deterministic_and_ordered():
    second_consumer = _consumer()
    second_consumer["capabilityId"] = "T.Widget.Reserve"
    fact_types = [_widget_fact()]
    forward = derive_data_dependencies(
        _documents([_producer(), _consumer(), second_consumer], fact_types)
    ).to_relations()
    reversed_order = derive_data_dependencies(
        _documents([second_consumer, _consumer(), _producer()], fact_types)
    ).to_relations()
    assert forward == reversed_order
    assert [relation["relationId"] for relation in forward] == sorted(
        relation["relationId"] for relation in forward
    )


def test_the_semantic_graph_reads_a_derived_relation_as_a_depends_on_edge():
    """3.3.2's cost argument, checked against the second reader rather than
    asserted.

    `graph.py:77-85` treats the relation vocabulary as closed: anything that is
    not `dependsOn` falls into the precondition branch and reads
    `requiredFactType`. A third relation kind would therefore not be additive at
    all — it would reroute into that branch and raise `KeyError`. An unknown
    *field* like `origin` passes straight through, which is what this asserts.
    """
    from sap_nexus_agent.semantic_planning.graph import SemanticGraphCompiler

    documents = _widget_documents()
    relations = list(derive_data_dependencies(documents).to_relations())
    assert relations, "nothing derived — the graph assertion would be vacuous"
    graph = SemanticGraphCompiler().compile(
        positive_control_documents(relations=relations)
    )
    assert (
        "dependsOn",
        CONSUMER_ID,
        PRODUCER_ID,
    ) in {
        (edge.relation_type, edge.source_id, edge.target_id) for edge in graph.edges
    }


def test_the_real_registry_renders_no_relations():
    """The empty case, reported as empty — task 3.5 requires exit 0 for it."""
    from sap_nexus_agent.semantic_planning import load_semantic_sources

    repo_root = Path(__file__).resolve().parents[2]
    view = derive_data_dependencies(load_semantic_sources(repo_root))
    assert view.to_relations() == ()
