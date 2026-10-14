"""Analysis runtime: wire entry, DAG execution, status aggregation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from sap_nexus_agent.ontology_planning.analysis_runtime import (
    run_analysis,
    sanitize_child_environment,
)
from sap_nexus_agent.ontology_planning.release import pin_release

REPO_ROOT = Path(__file__).resolve().parents[2]


def _wire() -> dict:
    pinned = pin_release(REPO_ROOT)
    return {
        "wireVersion": 1,
        "release": {
            "semanticSnapshotId": pinned.package.semantic_snapshot_id,
            "registrySnapshotId": pinned.package.registry_snapshot_id,
        },
        "nodeResults": [
            {
                "nodeId": "read-1",
                "capabilityId": "MM.PurchaseOrder.GetList",
                "parameters": {"material": "DEMOA2", "plant": "1000"},
                "gatewayTraceId": "fake-1",
                "executedAt": "2026-10-14T00:00:00Z",
                "data": {
                    "purchaseOrders": [
                        {"purchaseOrder": "4500000001", "supplier": "V72719",
                         "purchaseOrderUnit": "EA", "orderQuantity": "100",
                         "purchaseOrderItem": "00010"},
                        {"purchaseOrder": "4500000001", "supplier": "V72719",
                         "purchaseOrderUnit": "EA", "orderQuantity": "150",
                         "purchaseOrderItem": "00020"},
                    ]
                },
            }
        ],
        "analysisPlan": {
            "nodes": [
                {"nodeId": "a1", "operatorId": "group_sum",
                 "operatorVersion": "0.1.0",
                 "inputs": [
                     {"kind": "factField",
                      "factTypeId": "sapnexus:PurchaseOrderSupplyFact",
                      "field": "orderQuantity"}],
                 "params": {"dimensions": ["supplier"], "measure": "orderQuantity",
                            "unitField": "purchaseOrderUnit"},
                 "definitionRefs": [], "dependsOn": []}
            ],
            "outputs": ["a1"],
        },
        "requestedConclusions": [
            {"id": "c1", "statement": "grouped PO quantities",
             "evidenceRequirement": "lineage"}],
    }


def test_run_analysis_groups_and_enriches():
    pinned = pin_release(REPO_ROOT)
    envelope = run_analysis(_wire(), pinned)
    assert envelope["wireVersion"] == 1
    assert envelope["status"] == "complete"
    assert len(envelope["facts"]) == 2
    result = next(r for r in envelope["results"] if r["nodeId"] == "a1")
    assert result["status"] == "complete"
    assert result["rows"][0]["measures"]["orderQuantity"]["decimal"] == "250"
    assert envelope["uncoveredConclusions"] == []


def test_run_analysis_rejects_bad_wire_version():
    pinned = pin_release(REPO_ROOT)
    wire = _wire()
    wire["wireVersion"] = 2
    result = run_analysis(wire, pinned)
    assert result["status"] == "failed"


def test_sanitize_child_environment_strips_credentials():
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SAP_NEXUS_APPROVAL_TOKEN": "secret",
        "SAP_NEXUS_GATEWAY_URL": "http://gateway",
        "SAP_NEXUS_PRINCIPAL": "{}",
        "PYTHONPATH": "agent",
    }
    clean = sanitize_child_environment(env)
    assert "SAP_NEXUS_APPROVAL_TOKEN" not in clean
    assert "SAP_NEXUS_GATEWAY_URL" not in clean
    assert "SAP_NEXUS_PRINCIPAL" not in clean
    assert "PATH" in clean


def test_module_stdin_stdout_entry(tmp_path: Path):
    env = sanitize_child_environment({
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT / "agent"),
        "SAP_NEXUS_APPROVAL_TOKEN": "secret",
    })
    completed = subprocess.run(
        [sys.executable, "-m", "sap_nexus_agent.ontology_planning.analysis_runtime"],
        cwd=REPO_ROOT, env=env, input=json.dumps(_wire()),
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    envelope = json.loads(completed.stdout)
    assert envelope["status"] == "complete"
    assert envelope["results"][0]["rows"][0]["measures"]["orderQuantity"]["decimal"] == "250"


def test_module_rejects_malformed_json():
    env = sanitize_child_environment({**os.environ, "PYTHONPATH": str(REPO_ROOT / "agent")})
    completed = subprocess.run(
        [sys.executable, "-m", "sap_nexus_agent.ontology_planning.analysis_runtime"],
        cwd=REPO_ROOT, env=env, input=b"{not json",
        capture_output=True, timeout=30,
    )
    assert completed.returncode == 1
