"""End-to-end offline coordinator tests (Q1/Q2/Q3 and negative paths)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sap_nexus_agent.ontology_planning.coordinator import run_analysis_request

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "evals/ontology-read-analysis"
PRINCIPAL = {"principalId": "local-user-0001", "dataScope": {"tenantId": "default"}}


def _request(case_id: str) -> dict:
    return {
        "schemaVersion": 1,
        "caseId": case_id,
        "slots": {"material": "DEMOA2", "plant": "1000"},
        "scope": {"plant": "1000"},
        "interpreter": "fake",
        "principal": PRINCIPAL,
    }


@pytest.mark.parametrize("case_id", [
    "q1-stock-and-unit",
    "q2-po-group-by-supplier",
    "q3-supplier-filter",
])
def test_positive_cases_end_to_end(case_id):
    response = run_analysis_request(_request(case_id), REPO_ROOT, FIXTURES)
    assert response["status"] in {"complete", "partial"}, response
    assert response["writeGatewayCalls"] == 0
    assert response["releaseIds"]["registrySnapshotId"].startswith("sha256:")
    assert response["releaseIds"]["semanticSnapshotId"].startswith("sha256:")
    assert response["notRun"]


def test_q2_totals_and_lineage():
    response = run_analysis_request(_request("q2-po-group-by-supplier"), REPO_ROOT, FIXTURES)
    assert response["status"] == "complete"
    results = response["analysis"]["results"]
    group = next(r for r in results if r["nodeId"] == "a1")
    totals = {
        tuple(row["groupKey"].values())[0]: row["measures"]["orderQuantity"]["decimal"]
        for row in group["rows"]
    }
    assert totals == {"V72719": "250", "V88888": "40"}
    assert response["facts"]
    assert all("ATP" not in line and "available to promise" not in line.lower()
               for line in response["render"]["text"].splitlines())


def test_write_request_rejected_pre_gateway():
    request = _request("q1-stock-and-unit")
    request["draftOverride"] = {
        "schemaVersion": 1,
        "requestedFacts": [
            {"factTypeId": "sapnexus:PurchaseRequisitionCreatedFact",
             "fields": ["prNumber"], "objectSelectors": []}
        ],
        "constraints": [],
        "analysisNodes": [],
        "requestedConclusions": [
            {"id": "c1", "statement": "create PR", "evidenceRequirement": ""}],
        "assumptions": [],
    }
    response = run_analysis_request(request, REPO_ROOT, FIXTURES)
    assert response["status"] == "rejected"
    assert "WRITE_REJECTED" in response["reasons"]
    assert response["writeGatewayCalls"] == 0


def test_arrival_field_is_semantic_gap():
    request = _request("q1-stock-and-unit")
    request["draftOverride"] = {
        "schemaVersion": 1,
        "requestedFacts": [
            {"factTypeId": "sapnexus:PurchaseOrderSupplyFact",
             "fields": ["deliveryDate"],
             "objectSelectors": [
                 {"objectTypeId": "sapnexus:Material", "key": "material",
                  "value": "DEMOA2"},
                 {"objectTypeId": "sapnexus:Plant", "key": "plant",
                  "value": "1000"}]}
        ],
        "constraints": [],
        "analysisNodes": [],
        "requestedConclusions": [
            {"id": "c1", "statement": "arrivals next week", "evidenceRequirement": ""}],
        "assumptions": [],
    }
    response = run_analysis_request(request, REPO_ROOT, FIXTURES)
    assert response["status"] == "semantic_gap"
    assert response["writeGatewayCalls"] == 0
