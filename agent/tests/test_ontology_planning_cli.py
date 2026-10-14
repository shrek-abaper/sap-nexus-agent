"""Offline evidence CLI tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV = {**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "agent")}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m",
         "sap_nexus_agent.ontology_planning.cli", *args],
        cwd=REPO_ROOT, env=ENV, capture_output=True, text=True, timeout=60,
    )


def test_case_q1_json_exit_zero():
    result = _run("--case", "q1-stock-and-unit", "--json")
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["status"] in {"complete", "partial"}
    assert response["writeGatewayCalls"] == 0
    assert "plan" in response
    assert response["notRun"]


def test_case_text_mode():
    result = _run("--case", "q2-po-group-by-supplier")
    assert result.returncode == 0
    assert "Facts:" in result.stdout
    assert "Analysis:" in result.stdout


def test_bad_flag_exit_two():
    result = _run("--bogus")
    assert result.returncode == 2


def test_rejected_draft_exit_three(tmp_path: Path):
    request = {
        "schemaVersion": 1,
        "caseId": "q1-stock-and-unit",
        "slots": {"material": "DEMOA2", "plant": "1000"},
        "interpreter": "fake",
        "draftOverride": {
            "schemaVersion": 1,
            "requestedFacts": [
                {"factTypeId": "sapnexus:PurchaseRequisitionCreatedFact",
                 "fields": ["prNumber"], "objectSelectors": []}
            ],
            "constraints": [], "analysisNodes": [],
            "requestedConclusions": [
                {"id": "c1", "statement": "create", "evidenceRequirement": ""}],
            "assumptions": [],
        },
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    result = _run("--request-file", str(path), "--json")
    assert result.returncode == 3
    response = json.loads(result.stdout)
    assert response["status"] == "rejected"
