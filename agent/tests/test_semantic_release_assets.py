"""Schema tests for SemanticRelease authored asset documents."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

OPERATOR_IDS = {"select_fields", "filter_eq", "group_sum", "compare"}


def _schema(name: str) -> dict:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _yaml(rel: str) -> dict:
    return yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8"))


def test_analysis_versions_asset_validates():
    doc = _yaml("ontology/analysis-versions.yaml")
    jsonschema.validate(doc, _schema("analysis-versions.schema.json"))
    assert doc["compilerVersion"] == "0.1.0"
    assert set(doc["operatorImplementations"]) == OPERATOR_IDS


@pytest.mark.parametrize(
    "bad",
    [
        # missing operatorImplementations
        {"version": 1, "compilerVersion": "0.1.0"},
        # unknown top-level property
        {
            "version": 1,
            "compilerVersion": "0.1.0",
            "operatorImplementations": {"select_fields": "0.1.0"},
            "extra": 1,
        },
        # fifth operator key
        {
            "version": 1,
            "compilerVersion": "0.1.0",
            "operatorImplementations": {
                "select_fields": "0.1.0",
                "filter_eq": "0.1.0",
                "group_sum": "0.1.0",
                "compare": "0.1.0",
                "fifth_op": "0.1.0",
            },
        },
    ],
)
def test_analysis_versions_rejects_bad_shapes(bad):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, _schema("analysis-versions.schema.json"))


def test_object_types_asset_validates_and_uses_ontology_vocabulary():
    doc = _yaml("ontology/object-types.yaml")
    jsonschema.validate(doc, _schema("object-types.schema.json"))
    allowed = {
        "sapnexus:MaterialNumber",
        "sapnexus:Plant",
        "sapnexus:Supplier",
        "sapnexus:PurchaseOrderNumber",
        "sapnexus:PurchaseOrderItem",
        "sapnexus:CustomerNumber",
    }
    assert {o["semanticType"] for o in doc["objectTypes"]} <= allowed
    ids = [o["objectTypeId"] for o in doc["objectTypes"]]
    assert len(set(ids)) == len(ids)
    expected = {
        "sapnexus:Material",
        "sapnexus:Plant",
        "sapnexus:Supplier",
        "sapnexus:PurchaseOrder",
        "sapnexus:PurchaseOrderItem",
        "sapnexus:Customer",
    }
    assert set(ids) == expected


def test_object_types_reject_bad_shapes():
    schema = _schema("object-types.schema.json")
    with pytest.raises(jsonschema.ValidationError):
        # unknown property
        jsonschema.validate(
            {
                "version": 1,
                "objectTypes": [
                    {
                        "objectTypeId": "sapnexus:Material",
                        "semanticType": "sapnexus:MaterialNumber",
                        "keyFields": ["material"],
                        "scopeFields": [],
                        "extra": 1,
                    }
                ],
            },
            schema,
        )
    with pytest.raises(jsonschema.ValidationError):
        # empty keyFields
        jsonschema.validate(
            {
                "version": 1,
                "objectTypes": [
                    {
                        "objectTypeId": "sapnexus:Material",
                        "semanticType": "sapnexus:MaterialNumber",
                        "keyFields": [],
                        "scopeFields": [],
                    }
                ],
            },
            schema,
        )


def test_allowlist_triples_exist_in_fact_catalog():
    doc = _yaml("ontology/analysis-fact-fields.yaml")
    jsonschema.validate(doc, _schema("analysis-fact-fields.schema.json"))
    facts = {f["factTypeId"]: f for f in _yaml("ontology/fact-types.yaml")["factTypes"]}
    allowed_fact_types = {
        "sapnexus:InventoryAvailabilityFact",
        "sapnexus:PurchaseOrderSupplyFact",
        "sapnexus:MaterialInfoFact",
    }
    assert {e["factTypeId"] for e in doc["allowlist"]} == allowed_fact_types
    all_fields = set()
    for entry in doc["allowlist"]:
        catalog = facts[entry["factTypeId"]]
        catalog_fields = {f["name"]: f["semanticType"] for f in catalog["fields"]}
        for field in entry["fields"]:
            assert catalog_fields[field["name"]] == field["semanticType"]
            all_fields.add(field["name"])
    assert "mrpElementLines" not in all_fields


def test_allowlist_rejects_bad_shapes():
    schema = _schema("analysis-fact-fields.schema.json")
    valid_entry = {
        "factTypeId": "sapnexus:MaterialInfoFact",
        "fields": [
            {"name": "material", "semanticType": "sapnexus:MaterialNumber"},
        ],
    }
    with pytest.raises(jsonschema.ValidationError):
        # unknown property
        jsonschema.validate(
            {"version": 1, "allowlist": [{**valid_entry, "extra": 1}]},
            schema,
        )
    with pytest.raises(jsonschema.ValidationError):
        # duplicate field object inside one entry
        jsonschema.validate(
            {
                "version": 1,
                "allowlist": [
                    {
                        "factTypeId": "sapnexus:MaterialInfoFact",
                        "fields": [
                            {"name": "material", "semanticType": "sapnexus:MaterialNumber"},
                            {"name": "material", "semanticType": "sapnexus:MaterialNumber"},
                        ],
                    }
                ],
            },
            schema,
        )
    with pytest.raises(jsonschema.ValidationError):
        # empty fields
        jsonschema.validate(
            {"version": 1, "allowlist": [{"factTypeId": "x", "fields": []}]},
            schema,
        )


def test_operator_catalog_is_closed_four():
    doc = _yaml("ontology/analysis-operators.yaml")
    jsonschema.validate(doc, _schema("analysis-operators.schema.json"))
    ids = [o["operatorId"] for o in doc["operators"]]
    assert ids == ["select_fields", "filter_eq", "group_sum", "compare"]
    for operator in doc["operators"]:
        assert set(operator) <= {"operatorId", "version", "input", "output", "params", "constraints"}
        assert operator["version"] == "0.1.0"
        for param in operator["params"]:
            assert set(param) == {"name", "type", "required"}
        assert not any(
            key in operator or any(key in p for p in operator["params"])
            for key in ("path", "module", "expression", "code")
        )


def test_operator_catalog_rejects_bad_shapes():
    schema = _schema("analysis-operators.schema.json")
    base_operator = {
        "operatorId": "select_fields",
        "version": "0.1.0",
        "input": {"kind": "rows"},
        "output": {"kind": "rows"},
        "params": [
            {"name": "fields", "type": "fieldRefList", "required": True}
        ],
        "constraints": ["fields-must-be-allowlisted"],
    }
    with pytest.raises(jsonschema.ValidationError):
        # unknown property at operator level
        jsonschema.validate(
            {"version": 1, "operators": [{**base_operator, "path": "x"}]},
            schema,
        )
    with pytest.raises(jsonschema.ValidationError):
        # unknown property at param level
        bad = {
            **base_operator,
            "params": [{"name": "fields", "type": "fieldRefList",
                        "required": True, "expression": "x"}],
        }
        jsonschema.validate({"version": 1, "operators": [bad]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        # fifth operator
        fifth = {**base_operator, "operatorId": "join"}
        jsonschema.validate(
            {"version": 1, "operators": [
                {**base_operator, "operatorId": "select_fields"},
                {**base_operator, "operatorId": "filter_eq"},
                {**base_operator, "operatorId": "group_sum"},
                {**base_operator, "operatorId": "compare",
                 "output": {"kind": "comparison"}},
                fifth,
            ]},
            schema,
        )


def test_definition_applicability_empty_in_v1():
    doc = _yaml("ontology/definition-applicability.yaml")
    jsonschema.validate(doc, _schema("definition-applicability.schema.json"))
    assert doc["applicability"] == []


def test_definition_applicability_entry_shape():
    schema = _schema("definition-applicability.schema.json")
    valid = {
        "version": 1,
        "applicability": [
            {
                "definitionId": "sapnexus:def.available-for-commitment",
                "status": "grounded",
                "applicableScopes": ["MM"],
            }
        ],
    }
    jsonschema.validate(valid, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"version": 1, "applicability": [{"definitionId": "bad-id"}]},
            schema,
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {
                "version": 1,
                "applicability": [
                    {
                        "definitionId": "sapnexus:def.x",
                        "status": "unknown",
                        "applicableScopes": [],
                    }
                ],
            },
            schema,
        )


VALID_PACKAGE = {
    "schemaVersion": 1,
    "registrySnapshotId": "sha256:" + "a" * 64,
    "semanticSnapshotId": "sha256:" + "b" * 64,
    "compilerVersion": "0.1.0",
    "operatorImplementationVersion": {
        "select_fields": "0.1.0",
        "filter_eq": "0.1.0",
        "group_sum": "0.1.0",
        "compare": "0.1.0",
    },
    "sources": [
        {
            "path": "ontology/analysis-versions.yaml",
            "documentVersion": 1,
            "digest": "sha256:" + "c" * 64,
            "role": "semantic",
        }
    ],
    "businessValidity": {"applicability": []},
}


def test_semantic_release_package_schema_accepts_valid():
    jsonschema.validate(VALID_PACKAGE, _schema("semantic-release.schema.json"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=1),
        lambda d: d["sources"][0].update(extra=1),
        lambda d: d["sources"][0].update(role="other"),
        lambda d: d.update(registrySnapshotId="sha256:short"),
        lambda d: d.update(schemaVersion=2),
        lambda d: d["operatorImplementationVersion"].update(fifth="0.1.0"),
    ],
)
def test_semantic_release_package_schema_rejects_bad(mutate):
    import copy

    doc = copy.deepcopy(VALID_PACKAGE)
    mutate(doc)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, _schema("semantic-release.schema.json"))
