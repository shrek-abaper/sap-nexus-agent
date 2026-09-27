"""Tests for bad-case attribution rules and the review pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sap_nexus_agent.badcase_attribution import (
    BINDING,
    CALIBER,
    EXTRACTION,
    GOVERNANCE,
    REGISTRY_ALIAS,
    attribute_failure,
)
from sap_nexus_agent.badcase_pipeline import (
    build_review_artifact,
    is_mismatch,
    run_pipeline,
)


def _trace(
    trace_id="dtrace-1",
    decision="REJECT",
    capability_id=None,
    error_type="UNKNOWN_INTENT",
    missing=None,
    user_correction=False,
):
    return {
        "traceId": trace_id,
        "utteranceHash": "hash-1",
        "decision": decision,
        "capabilityId": capability_id,
        "errorType": error_type,
        "missingParameters": missing or [],
        "userCorrection": user_correction,
    }


# --- rule coverage -------------------------------------------------------------

def test_rule1_clarify_matched_capability_is_extraction():
    observed = _trace(
        decision="CLARIFY",
        capability_id="MM.Inventory.GetAvailability",
        error_type=None,
        missing=["plant"],
    )
    expected = {
        "expectedDecision": "SELECT",
        "expectedCapabilityId": "MM.Inventory.GetAvailability",
    }

    result = attribute_failure(observed, expected)

    assert result.category == EXTRACTION
    assert result.patch_target.endswith(".inputs")
    assert "plant" in result.rationale


def test_rule2_reject_unknown_intent_is_registry_alias():
    observed = _trace()
    expected = {
        "expectedDecision": "SELECT",
        "expectedCapabilityId": "MM.Inventory.GetAvailability",
    }

    result = attribute_failure(observed, expected)

    assert result.category == REGISTRY_ALIAS
    assert result.patch_target.endswith(".aliases")
    assert result.evidence_refs == ("dtrace-1",)


def test_rule2_clarify_wrong_capability_is_registry_alias():
    observed = _trace(decision="CLARIFY", capability_id="MM.PurchaseOrder.GetList")
    expected = {
        "expectedDecision": "SELECT",
        "expectedCapabilityId": "MM.Inventory.GetAvailability",
    }

    assert attribute_failure(observed, expected).category == REGISTRY_ALIAS


def test_rule3_caliber_mismatch():
    observed = _trace(
        decision="SELECT",
        capability_id="MM.Inventory.GetAvailability",
        error_type=None,
    )
    expected = {
        "expectedDecision": "SELECT",
        "expectedCapabilityId": "MM.Inventory.GetAvailability",
        "caliberMismatch": True,
        "expectedCaliberId": "MM.Inventory.AvailabilityForCommitment.v1",
    }

    result = attribute_failure(observed, expected)

    assert result.category == CALIBER
    assert result.patch_target == "ontology#MM.Inventory.AvailabilityForCommitment.v1"


def test_rule5_binding_error_types():
    for error_type in [
        "READ_EXECUTION_BINDING_MISMATCH",
        "SOURCE_LOAD_ERROR",
        "SNAPSHOT_DRIFT",
    ]:
        observed = _trace(decision="REJECT", error_type=error_type)
        expected = {"expectedDecision": "SELECT"}

        assert attribute_failure(observed, expected).category == BINDING


def test_rule4_expected_reject_got_select_is_governance():
    observed = _trace(
        decision="SELECT",
        capability_id="MM.Inventory.GetAvailability",
        error_type=None,
    )
    expected = {"expectedDecision": "REJECT"}

    assert attribute_failure(observed, expected).category == GOVERNANCE


def test_rule6_unclassified_is_governance():
    result = attribute_failure(
        _trace(decision="SHOW_OPTIONS", error_type=None),
        {"expectedDecision": "SELECT"},
    )

    assert result.category == GOVERNANCE


# --- pipeline ------------------------------------------------------------------

def test_is_mismatch_detection():
    assert is_mismatch(_trace(decision="REJECT"), {"expectedDecision": "SELECT"})
    assert not is_mismatch(
        _trace(decision="SELECT", capability_id="MM.Inventory.GetAvailability", error_type=None),
        {"expectedDecision": "SELECT", "expectedCapabilityId": "MM.Inventory.GetAvailability"},
    )


def test_build_review_artifact_shape():
    artifact = build_review_artifact(
        _trace(),
        {"expectedDecision": "SELECT", "expectedCapabilityId": "MM.Inventory.GetAvailability"},
    )

    assert artifact["schema"] == "sap-nexus.badcase-review.v1"
    assert artifact["status"] == "candidate"
    assert artifact["sourceTraceId"] == "dtrace-1"
    assert artifact["utterance"] is None
    assert artifact["clusterKey"].startswith("registry-alias|")
    assert artifact["attribution"]["category"] == REGISTRY_ALIAS


def test_run_pipeline_groups_clusters_and_corrections(tmp_path):
    traces = tmp_path / "traces.jsonl"
    traces.write_text(
        "\n".join([
            json.dumps(_trace("dtrace-1")),
            json.dumps(_trace(
                "dtrace-2", decision="REJECT", error_type="UNKNOWN_INTENT",
            )),
            json.dumps(_trace(
                "dtrace-3", decision="SELECT",
                capability_id="MM.PurchaseOrder.GetList", error_type=None,
                user_correction=True,
            )),
        ]),
        encoding="utf-8",
    )
    annotations = tmp_path / "annotations.json"
    annotations.write_text(json.dumps([
        {"traceId": "dtrace-1", "expectedDecision": "SELECT",
         "expectedCapabilityId": "MM.Inventory.GetAvailability"},
        {"traceId": "dtrace-2", "expectedDecision": "SELECT",
         "expectedCapabilityId": "MM.Inventory.GetAvailability"},
        # A matching annotation: must be skipped, not produce a candidate.
        {"traceId": "dtrace-3", "expectedDecision": "SELECT",
         "expectedCapabilityId": "MM.PurchaseOrder.GetList"},
    ]), encoding="utf-8")
    out = tmp_path / "review"

    summary = run_pipeline(
        traces_path=traces, annotations_path=annotations, output_dir=out
    )

    assert summary == {"candidates": 2, "clusters": 1, "corrections": 0}
    artifacts = list(out.glob("bc-candidate-*.json"))
    assert len(artifacts) == 2
    clusters = json.loads((out / "clusters.json").read_text("utf-8"))
    assert len(clusters["clusters"]) == 1
    assert len(clusters["clusters"][0]["caseIds"]) == 2


def test_pipeline_unknown_trace_raises(tmp_path):
    traces = tmp_path / "traces.jsonl"
    traces.write_text(json.dumps(_trace()), encoding="utf-8")
    annotations = tmp_path / "annotations.json"
    annotations.write_text(json.dumps([
        {"traceId": "dtrace-missing", "expectedDecision": "SELECT"},
    ]), encoding="utf-8")

    with pytest.raises(KeyError):
        run_pipeline(
            traces_path=traces,
            annotations_path=annotations,
            output_dir=tmp_path / "review",
        )
