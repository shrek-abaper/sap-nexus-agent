"""24-case offline contract matrix and sealed holdout harness."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from sap_nexus_agent.ontology_planning.coordinator import run_analysis_request

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS = REPO_ROOT / "evals/ontology-read-analysis"
PACKAGE = EVALS / "agent-package"

CASES = json.loads((EVALS / "cases.json").read_text(encoding="utf-8"))


def _request(case: dict) -> dict:
    return {
        "schemaVersion": 1,
        "caseId": case["gatewayCase"],
        "draftFile": case["draftFile"],
        # Per-case slots override: negative cases that exercise the resolver's
        # missing-selector path must withhold the slot explicitly now that
        # server slots authoritatively supplement the draft.
        "slots": case.get("slots", {"material": "DEMOA2", "plant": "1000"}),
        "scope": {"plant": "1000"},
        "interpreter": "fake",
        "principal": {"principalId": "local-user-0001",
                      "dataScope": {"tenantId": "default"}},
    }


def _reason_blob(response: dict) -> str:
    parts = list(response.get("reasons", []))
    plan = response.get("plan") or {}
    for result in response.get("analysis", {}).get("results", []):
        parts.extend(result.get("reasons", []))
    parts.extend(response.get("analysis", {}).get("conflicts", []))
    parts.extend(response.get("nodeFailures", []))
    return "\n".join(str(p) for p in parts)


def _predicate(response: dict, predicate: str) -> bool:
    analysis = response.get("analysis", {})
    if predicate.startswith("facts"):
        comparator = predicate.split("==" if "==" in predicate else ">=")[-1]
        count = len(response.get("facts", []))
        if predicate.endswith("==0"):
            return count == 0
        if ">=" in predicate:
            return count >= int(predicate.split(">=")[1])
    if predicate.startswith("facts=="):
        return len(response.get("facts", [])) == int(predicate.split("==")[1])
    if predicate.startswith("resultDecimal:"):
        _, node_id, expected = predicate.split(":")
        result = next(r for r in analysis["results"] if r["nodeId"] == node_id)
        decimals = [
            row["measures"]["orderQuantity"]["decimal"]
            for row in result["rows"]
        ]
        return expected in decimals
    if predicate.startswith("renderHasNo:"):
        text = response.get("render", {}).get("text", "")
        token = predicate.split(":", 1)[1]
        return token.lower() not in text.lower()
    if predicate.startswith("renderHas:"):
        token = predicate.split(":", 1)[1]
        return token in response.get("render", {}).get("text", "")
    if predicate.startswith("reasonPrefix:"):
        prefix = predicate.split(":", 1)[1]
        return any(str(r).startswith(prefix) for r in _reason_blob(response).splitlines())
    if predicate.startswith("reasonContains:"):
        token = predicate.split(":", 1)[1]
        return token in _reason_blob(response)
    if predicate.startswith("exclusionReason:"):
        reason = predicate.split(":", 1)[1]
        reasons = {e["reason"] for e in analysis.get("excludedRows", [])}
        reasons |= {e["reason"] for e in analysis.get("normalizationExclusions", [])}
        return reason in reasons
    raise AssertionError(f"unknown predicate: {predicate}")


def test_fixture_uncovered_object_returns_clarification_not_borrowed_numbers():
    # A free-form question about a real material must NOT be answered with the
    # fixture's DEMOA2 numbers: the offline sample covers only its declared
    # identity (gateway/identity.json).
    request = {
        "schemaVersion": 1,
        "caseId": "q1-stock-and-unit",
        "draftOverride": {
            "schemaVersion": 1,
            "requestedFacts": [
                {"factTypeId": "sapnexus:InventoryAvailabilityFact",
                 "fields": ["availableQuantity"],
                 "objectSelectors": [
                     {"objectTypeId": "sapnexus:Material", "key": "material", "value": "P0235094AE"},
                     {"objectTypeId": "sapnexus:Plant", "key": "plant", "value": "5260"}]},
            ],
            "constraints": [],
            "analysisNodes": [],
            "requestedConclusions": [
                {"id": "c1", "statement": "current stock", "evidenceRequirement": "fact values"}
            ],
            "assumptions": [],
        },
        "slots": {"material": "P0235094AE", "plant": "5260"},
        "interpreter": "fake",
    }
    response = run_analysis_request(request, REPO_ROOT, EVALS)
    assert response["status"] == "clarification"
    assert any(
        "OFFLINE_FIXTURE_OBJECT_NOT_COVERED:material=P0235094AE" in reason
        for reason in response["reasons"]
    ), response["reasons"]
    # The fixture's DEMOA2 numbers must never leak into the answer.
    assert "12.000" not in json.dumps(response, ensure_ascii=False)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_contract_case(case):
    response = run_analysis_request(_request(case), REPO_ROOT, EVALS)
    assert response["status"] == case["expectedStatus"], (
        case["id"], response["status"], response.get("reasons"),
        response.get("nodeFailures"),
    )
    assert response["writeGatewayCalls"] == case["writeGatewayCalls"]

    executed = set(response.get("executedCapabilities", []))
    assert executed == set(case["capabilities"]), (case["id"], executed)

    if case.get("operatorIds"):
        produced = [r["operatorId"] for r in response["analysis"]["results"]]
        for operator_id in case["operatorIds"]:
            assert operator_id in produced

    for predicate in case["assertions"]:
        assert _predicate(response, predicate), (case["id"], predicate)


def test_deterministic_twice():
    case = next(c for c in CASES if c["id"] == "q2-po-group-by-supplier")
    first = run_analysis_request(_request(case), REPO_ROOT, EVALS)
    second = run_analysis_request(_request(case), REPO_ROOT, EVALS)
    assert json.dumps(first["facts"], sort_keys=True) == json.dumps(
        second["facts"], sort_keys=True
    )
    assert first["plan"]["planId"] == second["plan"]["planId"]


def test_holdout_sealed_by_default():
    files = list((EVALS / "holdout").glob("cases-*.json"))
    assert files == []


def test_production_code_never_references_holdout_ids():
    package = REPO_ROOT / "agent/sap_nexus_agent/ontology_planning"
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "holdout/" not in node.value, path
