"""Strict-schema tests for ontology_planning v1 wire documents."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


VALID_DRAFT = {
    "schemaVersion": 1,
    "requestedFacts": [
        {"factTypeId": "sapnexus:InventoryAvailabilityFact",
         "fields": ["availableQuantity"],
         "objectSelectors": [
             {"objectTypeId": "sapnexus:Material", "key": "material",
              "value": "DEMOA2"}]}
    ],
    "constraints": [
        {"name": "plant", "semanticType": "sapnexus:Plant", "value": "1000",
         "source": "explicitUser"}
    ],
    "analysisNodes": [],
    "requestedConclusions": [
        {"id": "c1", "statement": "stock", "evidenceRequirement": "unit"}
    ],
    "assumptions": [],
}

VALID_PLAN = {
    "schemaVersion": 1,
    "planId": "sha256:" + "a" * 64,
    "semanticSnapshotId": "sha256:" + "b" * 64,
    "registrySnapshotId": "sha256:" + "c" * 64,
    "principalId": "local-user-0001",
    "scope": {"plant": "1000"},
    "readPlan": {
        "planGraphVersion": 2,
        "planId": "plan-1",
        "goalId": "g1",
        "executionMode": "READ_ONLY",
        "snapshotId": "sha256:" + "c" * 64,
        "nodes": [],
        "edges": [],
        "topologicalOrder": [],
        "goalOutputs": [],
        "readPartition": [],
        "actionPartition": [],
        "projectionRef": [],
        "ruleSetRefs": [],
    },
    "analysisPlan": {"nodes": [], "outputs": []},
    "limits": {},
    "freshness": {},
    "coverage": {"covered": [], "uncovered": []},
}

VALID_FACT = {
    "schemaVersion": 1,
    "factId": "node-1:row:0",
    "factTypeRef": "sapnexus:InventoryAvailabilityFact",
    "objectType": "InventoryStock",
    "objectKey": {"material": "DEMOA2", "plant": "1000"},
    "scope": {"plant": "1000"},
    "rowIdentity": {"material": "DEMOA2", "plant": "1000"},
    "fields": {
        "availableQuantity": {
            "value": "12.000", "semanticType": "sapnexus:AvailableQuantity"
        }
    },
    "unit": None,
    "businessTime": None,
    "collectedAt": "2026-10-14T00:00:00Z",
    "definitionRef": None,
    "evidence": {
        "runId": "run-1",
        "nodeId": "node-1",
        "gatewayTraceId": "fake-1",
        "rawFields": ["availableQuantity"],
        "completeness": "complete",
    },
}

VALID_RESULT = {
    "schemaVersion": 1,
    "nodeId": "a1",
    "operatorId": "group_sum",
    "status": "complete",
    "outputType": "groupedRows",
    "rows": [
        {"groupKey": {"supplier": "V72719"},
         "measures": {"orderQuantity": {"decimal": "250.000", "unit": "EA"}},
         "lineage": ["node-2:row:0", "node-2:row:1"]}
    ],
    "excludedRows": [],
    "operatorVersion": "0.1.0",
    "definitionRefs": [],
    "partial": False,
    "limits": {},
    "reasons": [],
}


@pytest.mark.parametrize(
    "schema_name,document",
    [
        ("semantic-goal-draft.schema.json", VALID_DRAFT),
        ("read-analysis-plan.schema.json", VALID_PLAN),
        ("typed-fact.schema.json", VALID_FACT),
        ("analysis-result.schema.json", ANALYSIS_RESULT := VALID_RESULT),
    ],
)
def test_valid_documents_pass(schema_name, document):
    jsonschema.validate(document, _schema(schema_name))


def test_draft_rejects_unknown_and_bad_source():
    schema = _schema("semantic-goal-draft.schema.json")
    bad = copy.deepcopy(VALID_DRAFT)
    bad["extra"] = 1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    bad = copy.deepcopy(VALID_DRAFT)
    bad["constraints"][0]["source"] = "model"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_plan_requires_read_only_and_empty_actions():
    schema = _schema("read-analysis-plan.schema.json")
    write_plan = copy.deepcopy(VALID_PLAN)
    write_plan["readPlan"]["executionMode"] = "PLAN_ONLY"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(write_plan, schema)
    write_plan = copy.deepcopy(VALID_PLAN)
    write_plan["readPlan"]["actionPartition"] = [{"nodeId": "x"}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(write_plan, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**VALID_PLAN, "clientVerified": True}, schema)


def test_fact_measure_is_string_and_statuses_closed():
    schema = _schema("typed-fact.schema.json")
    bad = copy.deepcopy(VALID_FACT)
    bad["fields"]["availableQuantity"]["value"] = 12.0
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    result_schema = _schema("analysis-result.schema.json")
    bad = copy.deepcopy(VALID_RESULT)
    bad["status"] = "maybe"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, result_schema)
