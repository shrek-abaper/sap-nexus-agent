"""Tests for the paired evaluation gate: metrics classification, comparison,
registry materialization, and the eval --metrics mode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sap_nexus_agent.eval import (
    _classify_case_slis,
    _run_legacy_metrics,
    run_metrics_file,
)
from sap_nexus_agent.paired_eval import (
    aggregate,
    compare_sli,
    git_commit,
    materialize_registry,
    run_paired,
    worktree_registry_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- SLI classification (D1) -------------------------------------------------

def test_classify_select_case_maps_hit_and_parameter():
    decision, slis = _classify_case_slis({"expectedDecision": "SELECT"})

    assert decision == "SELECT"
    assert slis == ["capabilityHitRate", "parameterCompletionRate"]


def test_classify_select_with_caliber_maps_caliber_accuracy():
    decision, slis = _classify_case_slis({
        "expectedDecision": "SELECT",
        "expectedBusinessCaliber": {"caliberId": "cal.v1"},
    })

    assert "businessCaliberAccuracy" in slis


def test_classify_clarify_and_reject():
    assert _classify_case_slis({"expectedDecision": "CLARIFY"}) == (
        "CLARIFY", ["missingParameterClarificationRate"]
    )
    assert _classify_case_slis({"expectedDecision": "REJECT"}) == (
        "REJECT", ["unsafeExecutionBlockRate"]
    )


def test_classify_legacy_status_and_matcher_decision_type():
    assert _classify_case_slis({"expected": {"status": "success"}})[1] == [
        "capabilityHitRate", "parameterCompletionRate",
    ]
    assert _classify_case_slis({"expected": {"decisionType": "REJECT"}}) == (
        "REJECT", ["unsafeExecutionBlockRate"]
    )
    assert _classify_case_slis({"expected": {"decisionType": "ESCALATE_TO_PLANNER"}})[1] == []


def test_classify_governed_multi_turn_union():
    case = {
        "fixtureVersion": "governed-read-context-v1",
        "turns": [
            {"expected": {"decision": "SELECT"}},
            {"expected": {"decision": "CLARIFY"}},
            {"expected": {"decision": "SELECT"}},
        ],
    }

    decision, slis = _classify_case_slis(case)

    assert decision == "MULTI_TURN"
    assert slis == ["capabilityHitRate", "missingParameterClarificationRate",
                    "parameterCompletionRate"]


# --- aggregation and comparison ----------------------------------------------

def _counts(passed: int, total: int) -> dict[str, dict[str, int]]:
    return {
        "capabilityHitRate": {"passed": passed, "total": total},
        "missingParameterClarificationRate": {"passed": 0, "total": 0},
    }


def test_compare_equal_counts_passes():
    sli, regressed = compare_sli(_counts(10, 10), _counts(10, 10))

    assert regressed == []
    assert sli["capabilityHitRate"]["delta"] == 0
    assert sli["capabilityHitRate"]["regressed"] is False


def test_compare_negative_delta_fails():
    sli, regressed = compare_sli(_counts(10, 10), _counts(9, 10))

    assert regressed == ["capabilityHitRate"]
    assert sli["capabilityHitRate"]["delta"] == pytest.approx(-0.1)
    assert sli["capabilityHitRate"]["regressed"] is True


def test_compare_positive_delta_passes():
    sli, regressed = compare_sli(_counts(9, 10), _counts(10, 10))

    assert regressed == []
    assert sli["capabilityHitRate"]["delta"] == pytest.approx(0.1)


def test_compare_denominator_mismatch_fails():
    sli, regressed = compare_sli(_counts(10, 10), _counts(10, 11))

    assert regressed == ["capabilityHitRate"]
    assert sli["capabilityHitRate"]["reason"] == "denominator mismatch"


def test_compare_zero_denominator_not_gated():
    sli, regressed = compare_sli(_counts(0, 0), _counts(0, 0))

    assert regressed == []
    assert sli["capabilityHitRate"]["delta"] is None
    assert sli["capabilityHitRate"]["reason"] == "zero denominator"


def test_aggregate_sums_suite_counts():
    counts = aggregate([
        {"sli": {"capabilityHitRate": {"passed": 3, "total": 4}}},
        {"sli": {"capabilityHitRate": {"passed": 5, "total": 6}}},
    ])

    assert counts["capabilityHitRate"] == {"passed": 8, "total": 10}


# --- metrics mode -------------------------------------------------------------

def test_run_metrics_file_inventory_all_pass():
    payload = run_metrics_file(REPO_ROOT / "evals/inventory_availability_cases.yaml")

    assert payload["suite"] == "inventory_availability_cases"
    assert payload["cases"]
    assert all(c["passed"] for c in payload["cases"])
    assert payload["sli"]["capabilityHitRate"]["total"] >= 1


def test_metrics_records_failure_without_aborting():
    # Happy-path utterance but an assertion guaranteed to fail (wrong status).
    case = {
        "id": "synthetic-wrong-status",
        "userQuery": "DEMOA1 在 1000 还有多少可用库存？",
        "expected": {"status": "clarification", "validateCalls": 0, "executeCalls": 0},
    }

    observed, counts = _run_legacy_metrics([case])

    assert observed[0]["passed"] is False
    assert observed[0]["error"]
    assert counts["missingParameterClarificationRate"] == {"passed": 0, "total": 1}


# --- registry materialization -------------------------------------------------

def test_materialize_registry_from_head(tmp_path):
    files = materialize_registry("HEAD", REPO_ROOT, tmp_path)

    assert "registry/capabilities.yaml" in files
    materialized = tmp_path / "registry/capabilities.yaml"
    assert materialized.read_bytes() == (REPO_ROOT / "registry/capabilities.yaml").read_bytes()


def test_worktree_files_hash_current_registry():
    files = worktree_registry_files(REPO_ROOT)

    assert files["registry/capabilities.yaml"]


# --- end-to-end gate -----------------------------------------------------------

def test_run_paired_clean_tree_passes(tmp_path):
    report, report_path = run_paired(
        repo_root=REPO_ROOT,
        parent_ref="HEAD",
        output_dir=tmp_path,
    )

    try:
        assert report["decision"] == "PASS"
        assert report["regressedSlis"] == []
        assert report["parent"]["commit"] == git_commit(REPO_ROOT, "HEAD")
        assert report["candidate"]["ref"] == "worktree"
        assert report_path.exists()
        loaded = json.loads(report_path.read_text("utf-8"))
        assert loaded["schema"] == "sap-nexus.paired-eval-report.v1"
    finally:
        report_path.unlink(missing_ok=True)
