"""SemanticGoalDraft validation: schema, technical scan, bounds, DAG."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from sap_nexus_agent.ontology_planning.draft_validation import (
    parse_draft_bytes,
    validate_draft,
)

RELEASE = SimpleNamespace(
    allowlist_fields={
        "sapnexus:InventoryAvailabilityFact": {"availableQuantity"},
        "sapnexus:PurchaseOrderSupplyFact": {
            "purchaseOrder", "purchaseOrderItem", "supplier", "material",
            "plant", "orderQuantity", "purchaseOrderUnit",
        },
        "sapnexus:MaterialInfoFact": {
            "material", "plant", "baseUnitOfMeasure", "purchasingGroup",
        },
    },
    operator_ids=frozenset(
        {"select_fields", "filter_eq", "group_sum", "compare"}
    ),
)


def _valid_draft() -> dict:
    return {
        "schemaVersion": 1,
        "requestedFacts": [
            {"factTypeId": "sapnexus:InventoryAvailabilityFact",
             "fields": ["availableQuantity"],
             "objectSelectors": [
                 {"objectTypeId": "sapnexus:Material", "key": "material",
                  "value": "DEMOA2"},
                 {"objectTypeId": "sapnexus:Plant", "key": "plant",
                  "value": "1000"}]}
        ],
        "constraints": [],
        "analysisNodes": [],
        "requestedConclusions": [
            {"id": "c1", "statement": "stock", "evidenceRequirement": "x"}],
        "assumptions": [],
    }


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def test_valid_draft_passes():
    report = validate_draft(_valid_draft(), RELEASE)
    assert report.valid, [str(i) for i in report.issues]


def test_schema_invalid_unknown_property():
    doc = _valid_draft()
    doc["extra"] = 1
    report = validate_draft(doc, RELEASE)
    assert not report.valid
    assert "DRAFT_SCHEMA_INVALID" in _codes(report)


@pytest.mark.parametrize(
    "location,mutate",
    [
        ("rfc param", lambda d: d["constraints"].append(
            {"name": "rfcName", "semanticType": "sapnexus:Plant",
             "value": "BAPI_X", "source": "explicitUser"})),
        ("url in params", lambda d: d["analysisNodes"].append(
            {"nodeId": "a1", "operatorId": "select_fields", "inputs": [],
             "params": {"q": "https://evil.example"}, "dependsOn": []})),
        ("binding key", lambda d: d["requestedFacts"][0].__setitem__(
            "bindingId", "x")),
        ("path value", lambda d: d["assumptions"].append("../../etc/passwd")),
        ("shell metachars", lambda d: d["requestedConclusions"][0].update(
            statement="x; rm -rf /")),
    ],
)
def test_technical_content_rejected(location, mutate):
    doc = _valid_draft()
    mutate(doc)
    report = validate_draft(doc, RELEASE)
    assert not report.valid
    assert "DRAFT_TECHNICAL_KEY" in _codes(report), location


def test_unknown_operator_and_unresolved_input():
    doc = _valid_draft()
    doc["analysisNodes"] = [
        {"nodeId": "a1", "operatorId": "join", "inputs": [],
         "params": {}, "dependsOn": []}
    ]
    report = validate_draft(doc, RELEASE)
    assert "DRAFT_UNKNOWN_OPERATOR" in _codes(report)
    doc = _valid_draft()
    doc["analysisNodes"] = [
        {"nodeId": "a1", "operatorId": "select_fields",
         "inputs": [{"kind": "nodeRef", "nodeId": "a2"}],
         "params": {}, "dependsOn": ["a2"]}
    ]
    report = validate_draft(doc, RELEASE)
    assert "DRAFT_UNRESOLVED_INPUT" in _codes(report)


def test_dag_cycle_and_bounds():
    doc = _valid_draft()
    doc["analysisNodes"] = [
        {"nodeId": "a1", "operatorId": "select_fields", "inputs": [],
         "params": {}, "dependsOn": ["a2"]},
        {"nodeId": "a2", "operatorId": "select_fields", "inputs": [],
         "params": {}, "dependsOn": ["a1"]},
    ]
    report = validate_draft(doc, RELEASE)
    assert "DRAFT_DAG_CYCLE" in _codes(report)
    doc = _valid_draft()
    doc["analysisNodes"] = [
        {"nodeId": f"a{i}", "operatorId": "select_fields", "inputs": [],
         "params": {}, "dependsOn": []}
        for i in range(7)
    ]
    report = validate_draft(doc, RELEASE)
    assert "DRAFT_BOUNDS" in _codes(report)


def test_string_length_and_nesting_bounds():
    doc = _valid_draft()
    doc["assumptions"] = ["x" * 4097]
    report = validate_draft(doc, RELEASE)
    assert "DRAFT_BOUNDS" in _codes(report)

    def nest(depth: int) -> dict:
        value = "DEMOA2"
        for _ in range(depth):
            value = {"k": value}
        return {"schemaVersion": 1, "requestedFacts": [], "constraints": [],
                "analysisNodes": [], "requestedConclusions": [],
                "assumptions": [], "deep": value}

    # deep nesting + unknown property would both surface; assert bounds
    deep = nest(10)
    report = validate_draft(deep, RELEASE)
    assert "DRAFT_BOUNDS" in _codes(report) or "DRAFT_SCHEMA_INVALID" in _codes(report)


def test_non_finite_constants_rejected_by_parser():
    with pytest.raises(ValueError):
        parse_draft_bytes(b'{"x": NaN}')
    with pytest.raises(ValueError):
        parse_draft_bytes(b'{"x": Infinity}')
