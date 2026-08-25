"""Derive producer→consumer data dependency edges from the registry alone.

**Invariant 3.** A data dependency edge is *computed* by matching a Fact Type's
declared fields against capability signatures. Hand-writing such an edge into
`ontology/capability-relations.yaml` to make that file look non-empty is
forbidden: the file carries only relations that cannot be inferred from data
shape, and the acceptance criterion is that *this* view is non-empty.

**Invariant 2.** This module authors, it never executes. It performs no model
call, no Gateway call and no SAP call — deriving a parameter must never become a
reason to fetch a value during intent parsing. The import set is deliberately
tiny and is locked as a subset of an allowlist by
`agent/tests/test_derived_dependencies.py`, so any future import has to argue
for itself.

Candidate scoping, in order:

1. The consuming input declares ``satisfiableByFactType: F``.
2. ``F``'s declared fields are searched for one whose ``semanticType`` equals
   the input's. Scoping to ``F`` is load-bearing: a field of the same semantic
   type in another Fact Type is not a candidate.
3. The candidate producers are the **active** capabilities publishing an output
   with ``factTypeRef == F`` and the same ``semanticType``.

``required`` is not part of the scoping. The deriver reports what *can* be
derived; whether the planner pulls a producer node in is an authoring policy
belonging to ``plan_compiler_v2``.

Non-derivable shapes — no match, more than one match, or a ``cardinality: many``
field the deriver would have to reduce — are skipped rather than resolved. The
deriver never picks by declaration order. Task 3.4 turns each skip into an
explicit diagnostic.

**Rendering (task 3.3).** ``to_relations()`` projects the view into the shape
``ontology/capability-relations.yaml`` already defines for ``dependsOn``, so
``plan_compiler_v2``'s third pass consumes a derived dependency with no change
at all. Derivedness travels as an ``origin`` *field*, never as a new relation
kind: ruling ① keeps the relation catalog at ``dependsOn`` + ``precondition``,
additive only. The projection is in-memory — writing it back into the catalog is
exactly what invariant 3 forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import SemanticSourceDocuments

#: Derived edges reuse the existing relation kind (ruling ①); they never add one.
DERIVED_RELATION_TYPE = "dependsOn"
#: Provenance marker. Task 3.6 admits it in the schema alongside ``manual``.
DERIVED_ORIGIN = "derived"


@dataclass(frozen=True, order=True)
class DerivedDataEdge:
    """One producer→consumer parameter derivation, with its full provenance.

    ``fact_field_name`` and ``producer_output_name`` are equal under the C5
    publication rule but describe different layers: the runtime reads the field
    off the projected Fact, while the output name is what the Gateway returned.
    """

    consumer_capability_id: str
    consumer_input_name: str
    producer_capability_id: str
    producer_output_name: str
    fact_type_id: str
    fact_field_name: str
    semantic_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "consumerCapabilityId": self.consumer_capability_id,
            "consumerInputName": self.consumer_input_name,
            "producerCapabilityId": self.producer_capability_id,
            "producerOutputName": self.producer_output_name,
            "factTypeId": self.fact_type_id,
            "factFieldName": self.fact_field_name,
            "semanticType": self.semantic_type,
        }

    @property
    def relation_id(self) -> str:
        """Stable id naming both endpoints, so a reader can recompute it.

        Derived from the capability pair rather than a counter: a counter would
        renumber when documents are reordered, making a diff of the derived view
        unreadable. The id is opaque — nothing parses it back apart.
        """
        return (
            f"derived.dependsOn."
            f"{self.consumer_capability_id}~{self.producer_capability_id}"
        )

    def to_relation(self) -> dict[str, Any]:
        """Render as a ``dependsOn`` relation: the consumer depends on the
        producer, so the consumer is ``capabilityId`` and the producer is
        ``dependsOnCapabilityId``."""
        return {
            "relationId": self.relation_id,
            "relationType": DERIVED_RELATION_TYPE,
            "capabilityId": self.consumer_capability_id,
            "dependsOnCapabilityId": self.producer_capability_id,
            "origin": DERIVED_ORIGIN,
        }


@dataclass(frozen=True)
class DerivedDependencyView:
    edges: tuple[DerivedDataEdge, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"edges": [edge.to_dict() for edge in self.edges]}

    def to_relations(self) -> tuple[dict[str, Any], ...]:
        """Render the view as ``dependsOn`` relations, one per capability pair.

        A dependsOn relation is capability-level, not parameter-level: two
        derived parameters flowing from the same producer are one dependency.
        Rendering both would make the compiler author two identical
        ``dependency`` edges, and the S1 validator expects exactly one.
        ``edges`` is already sorted, so insertion order is deterministic.
        """
        relations: dict[str, dict[str, Any]] = {}
        for edge in self.edges:
            relations.setdefault(edge.relation_id, edge.to_relation())
        return tuple(relations.values())


def derive_data_dependencies(
    documents: SemanticSourceDocuments,
) -> DerivedDependencyView:
    """Derive producer→consumer data edges by strict semantic-type equality.

    No model call. No Gateway call. No SAP call. Deterministic.
    """
    fact_types = {
        fact_type["factTypeId"]: fact_type
        for fact_type in _items(documents.fact_types, "factTypes")
        if isinstance(fact_type, Mapping)
        and isinstance(fact_type.get("factTypeId"), str)
    }
    active = _active_capabilities(documents)
    producers = _producers_by_fact_type_and_semantic_type(active)

    edges: list[DerivedDataEdge] = []
    for capability in active:
        consumer_id = capability.get("capabilityId")
        if not isinstance(consumer_id, str):
            continue
        for input_field in capability.get("inputs") or ():
            if not isinstance(input_field, Mapping):
                continue
            fact_type_id = input_field.get("satisfiableByFactType")
            input_name = input_field.get("name")
            semantic_type = input_field.get("semanticType")
            if not (
                isinstance(fact_type_id, str)
                and isinstance(input_name, str)
                and isinstance(semantic_type, str)
            ):
                continue
            fact_type = fact_types.get(fact_type_id)
            if fact_type is None:
                # UNKNOWN_FACT_TYPE is the validator's diagnostic. The deriver
                # stays usable on documents the validator has already rejected.
                continue
            field_names = _matching_field_names(fact_type, semantic_type)
            if len(field_names) != 1:
                continue
            candidates = tuple(
                candidate
                for candidate in producers.get((fact_type_id, semantic_type), ())
                if candidate[0] != consumer_id
            )
            if len(candidates) != 1:
                continue
            producer_id, output_name = candidates[0]
            edges.append(
                DerivedDataEdge(
                    consumer_capability_id=consumer_id,
                    consumer_input_name=input_name,
                    producer_capability_id=producer_id,
                    producer_output_name=output_name,
                    fact_type_id=fact_type_id,
                    fact_field_name=field_names[0],
                    semantic_type=semantic_type,
                )
            )
    return DerivedDependencyView(edges=tuple(sorted(edges)))


def _matching_field_names(
    fact_type: Mapping[str, Any], semantic_type: str
) -> tuple[str, ...]:
    """Field names of this Fact Type that can bind a scalar of this type.

    A ``cardinality: many`` field is excluded rather than reduced: turning a
    list into a scalar needs an operator, and choosing one is not the deriver's
    decision to make.
    """
    return tuple(
        field["name"]
        for field in fact_type.get("fields") or ()
        if isinstance(field, Mapping)
        and isinstance(field.get("name"), str)
        and field.get("semanticType") == semantic_type
        and field.get("cardinality") == "one"
    )


def _active_capabilities(
    documents: SemanticSourceDocuments,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        capability
        for capability in _items(documents.capabilities, "capabilities")
        if isinstance(capability, Mapping) and capability.get("status") == "active"
    )


def _producers_by_fact_type_and_semantic_type(
    capabilities: tuple[Mapping[str, Any], ...],
) -> dict[tuple[str, str], tuple[tuple[str, str], ...]]:
    index: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for capability in capabilities:
        capability_id = capability.get("capabilityId")
        if not isinstance(capability_id, str):
            continue
        for output in capability.get("outputs") or ():
            if not isinstance(output, Mapping):
                continue
            fact_type_ref = output.get("factTypeRef")
            name = output.get("name")
            semantic_type = output.get("semanticType")
            if not (
                isinstance(fact_type_ref, str)
                and isinstance(name, str)
                and isinstance(semantic_type, str)
            ):
                continue
            index.setdefault((fact_type_ref, semantic_type), []).append(
                (capability_id, name)
            )
    return {key: tuple(sorted(value)) for key, value in index.items()}


def _items(document: Any, key: str) -> tuple[Any, ...]:
    if not isinstance(document, Mapping):
        return ()
    values = document.get(key)
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(values)
