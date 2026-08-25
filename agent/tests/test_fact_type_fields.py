"""Authoritative Fact Type field lists (T1: tasks 2.1 + 2.5).

Requirement: openspec/changes/derived-parameter-binding/specs/
registry-ontology-contract/spec.md — a Fact Type SHALL declare its fields
authoritatively so that data dependency edges can be *derived* by matching
field semantic types instead of being hand-written.

Three rules are pinned here:

1. Schema (2.1) — `fields` is required for every Fact Type, each entry carrying
   `name` / `semanticType` / `cardinality` / `optional` / `description`, and the
   catalog `version` is `2` because a newly-required key is breaking.
2. Vocabulary (2.1.4) — a field's `semanticType` is drawn from the `sapnexus:*`
   ontology vocabulary, i.e. the set declared by capability inputs/outputs. A
   bare matcher-catalog id such as `Unit` is not a semantic type.
3. Publication (2.5.4, correction C5) — a `cardinality: one` field must be
   published as a same-named, same-`semanticType` output by at least one active
   producer. `cardinality: many` fields are exempt: they describe items inside
   an array payload, whose container output name is deliberately not a field.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from sap_nexus_agent.semantic_planning import (
    SemanticSourceDocuments,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

REPO_ROOT = Path(__file__).resolve().parents[2]

FIELD_KEYS = {"name", "semanticType", "cardinality", "optional", "description"}


def _catalog() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "ontology" / "fact-types.yaml").read_text(encoding="utf-8")
    )


def _schema() -> dict:
    return json.loads(
        (REPO_ROOT / "schemas" / "fact-type-catalog.schema.json").read_text(
            encoding="utf-8"
        )
    )


def _mutable(value):
    if isinstance(value, dict):
        return {key: _mutable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mutable(item) for item in value]
    return value


def _sources_with_catalog(catalog: dict) -> SemanticSourceDocuments:
    base = load_semantic_sources(REPO_ROOT)
    return SemanticSourceDocuments(
        capabilities=_mutable(base.capabilities),
        executor_bindings=_mutable(base.executor_bindings),
        fact_types=catalog,
        relations=_mutable(base.relations),
    )


def _fact_type(catalog: dict, fact_type_id: str) -> dict:
    return next(
        item for item in catalog["factTypes"] if item["factTypeId"] == fact_type_id
    )


def _issue_codes(result) -> set[str]:
    return {issue.code for issue in result.report.issues}


# ---- 2.1: schema ----


def test_catalog_declares_fields_for_every_fact_type():
    catalog = _catalog()
    jsonschema.validate(catalog, _schema())
    assert catalog["version"] == 2
    for fact_type in catalog["factTypes"]:
        fields = fact_type.get("fields")
        assert fields, f"{fact_type['factTypeId']}: fields must be non-empty"
        for field in fields:
            assert set(field) == FIELD_KEYS, fact_type["factTypeId"]
            assert field["cardinality"] in {"one", "many"}
            assert isinstance(field["optional"], bool)


def test_schema_rejects_a_fact_type_without_fields():
    catalog = _catalog()
    del catalog["factTypes"][0]["fields"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(catalog, _schema())


def test_schema_rejects_an_unknown_cardinality():
    catalog = _catalog()
    catalog["factTypes"][0]["fields"][0]["cardinality"] = "several"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(catalog, _schema())


def test_schema_pins_the_catalog_version_to_two():
    catalog = _catalog()
    catalog["version"] = 1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(catalog, _schema())


def test_snapshot_reads_the_bumped_document_version():
    """2.1.6 — `document_version=int(document["version"])` is unconstrained, so
    it will read 2; assert it rather than assume it."""
    sources = load_semantic_sources(REPO_ROOT)
    result = build_semantic_contracts(sources)
    assert result.report.valid, [i.message for i in result.report.issues]
    versions = {
        source.path: source.document_version for source in result.snapshot.sources
    }
    assert versions["ontology/fact-types.yaml"] == 2


# ---- 2.1.4/2.1.5: the field semanticType must be ontology vocabulary ----


def test_bare_matcher_catalog_id_is_rejected_naming_fact_type_and_field():
    catalog = _catalog()
    fact_type = _fact_type(catalog, "sapnexus:InventoryAvailabilityFact")
    fact_type["fields"][0]["semanticType"] = "Unit"

    result = build_semantic_contracts(_sources_with_catalog(catalog))

    assert not result.report.valid
    messages = [
        issue.message
        for issue in result.report.issues
        if issue.code == "UNKNOWN_SEMANTIC_TYPE"
    ]
    assert messages, _issue_codes(result)
    assert any(
        "sapnexus:InventoryAvailabilityFact" in message
        and fact_type["fields"][0]["name"] in message
        for message in messages
    ), messages


def test_unknown_ontology_semantic_type_is_rejected():
    catalog = _catalog()
    _fact_type(catalog, "sapnexus:PurchaseRequisitionCreatedFact")["fields"][0][
        "semanticType"
    ] = "sapnexus:Nonexistent"

    result = build_semantic_contracts(_sources_with_catalog(catalog))

    assert not result.report.valid
    assert "UNKNOWN_SEMANTIC_TYPE" in _issue_codes(result)


# ---- 2.5.4 / C5: the publication invariant ----


def test_cardinality_one_field_must_be_published_by_an_active_producer():
    catalog = _catalog()
    fact_type = _fact_type(catalog, "sapnexus:PurchaseRequisitionCreatedFact")
    published = copy.deepcopy(fact_type["fields"][0])
    assert published["cardinality"] == "one"
    # Rename it so no producer output carries that name any more.
    fact_type["fields"][0]["name"] = published["name"] + "Renamed"

    result = build_semantic_contracts(_sources_with_catalog(catalog))

    assert not result.report.valid
    assert "UNPUBLISHED_FACT_FIELD" in _issue_codes(result)


def test_cardinality_one_field_must_match_the_producer_output_semantic_type():
    catalog = _catalog()
    fact_type = _fact_type(catalog, "sapnexus:InventoryAvailabilityFact")
    one_field = next(f for f in fact_type["fields"] if f["cardinality"] == "one")
    one_field["semanticType"] = "sapnexus:Plant"

    result = build_semantic_contracts(_sources_with_catalog(catalog))

    assert not result.report.valid
    assert "UNPUBLISHED_FACT_FIELD" in _issue_codes(result)


def test_cardinality_many_fields_are_exempt_from_publication():
    """`PurchaseOrderSupplyFact`'s item fields have no same-named output — the
    container output is `purchaseOrders` — and that is legitimate."""
    catalog = _catalog()
    fact_type = _fact_type(catalog, "sapnexus:PurchaseOrderSupplyFact")
    assert fact_type["fields"], "expected item fields to be declared"
    assert all(field["cardinality"] == "many" for field in fact_type["fields"])
    assert not any(
        field["name"] == "purchaseOrders" for field in fact_type["fields"]
    ), "the array container output name must not be declared as a field"

    result = build_semantic_contracts(_sources_with_catalog(catalog))

    assert result.report.valid, [i.message for i in result.report.issues]


def test_published_catalog_satisfies_the_publication_invariant():
    result = build_semantic_contracts(load_semantic_sources(REPO_ROOT))
    assert result.report.valid, [i.message for i in result.report.issues]
