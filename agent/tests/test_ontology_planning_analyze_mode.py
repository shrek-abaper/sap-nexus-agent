"""--mode analyze stdin entry for the DSH ontology tool."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV = {k: v for k, v in os.environ.items()}
ENV["PYTHONPATH"] = str(REPO_ROOT / "agent")


def _run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m",
         "sap_nexus_agent.ontology_planning.analysis_runtime",
         "--mode", "analyze"],
        cwd=REPO_ROOT, env=ENV, input=json.dumps(payload),
        capture_output=True, text=True, timeout=60,
    )


def test_analyze_mode_q1_complete():
    result = _run({
        "schemaVersion": 1,
        "caseId": "q1-stock-and-unit",
        "interpreter": "fake",
        "slots": {"material": "DEMOA2", "plant": "1000"},
        "scope": {"plant": "1000"},
    })
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["status"] == "complete"
    assert response["writeGatewayCalls"] == 0


def test_analyze_mode_q5_gap():
    result = _run({
        "schemaVersion": 1,
        "caseId": "q5-arrivals-next-week",
        "interpreter": "fake",
        "slots": {"material": "DEMOA2", "plant": "1000"},
    })
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "semantic_gap"


def test_analyze_mode_write_rejected_exit_three():
    result = _run({
        "schemaVersion": 1,
        "caseId": "write-create-pr",
        "interpreter": "fake",
        "slots": {},
    })
    assert result.returncode == 3
    assert json.loads(result.stdout)["status"] == "rejected"


def test_analyze_mode_malformed_exit_one():
    result = subprocess.run(
        [sys.executable, "-m",
         "sap_nexus_agent.ontology_planning.analysis_runtime",
         "--mode", "analyze"],
        cwd=REPO_ROOT, env=ENV, input=b"{bad json",
        capture_output=True, timeout=60,
    )
    assert result.returncode == 1
