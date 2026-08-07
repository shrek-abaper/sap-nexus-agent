import json
from pathlib import Path

import pytest

from sap_nexus_agent.eval import FakeGatewayClient, run_eval_file

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_inventory_eval_file_passes():
    summary = run_eval_file(REPO_ROOT / "evals" / "inventory_availability_cases.yaml")

    assert summary.total >= 6
    assert summary.failed == 0
    assert summary.passed == summary.total


def test_eval_harness_seed_cases_pass_contract():
    summary = run_eval_file(REPO_ROOT / "evals" / "eval_harness_seed_cases.json")

    assert summary.total >= 13
    assert summary.failed == 0
    assert summary.passed == summary.total


def test_pr_create_eval_file_passes():
    summary = run_eval_file(REPO_ROOT / "evals" / "pr_create_cases.json")

    assert summary.total == 9
    assert summary.failed == 0
    assert summary.passed == summary.total


def test_po_seed_cases_route_via_run_query():
    """PO seed cases (bc_mm_purchaseorder_*) route through run_query and pass."""
    import json

    payload = json.loads((REPO_ROOT / "evals" / "eval_harness_seed_cases.json").read_text("utf-8"))
    po_case_ids = [c["caseId"] for c in payload["cases"] if c["caseId"].startswith("bc_mm_purchaseorder_")]
    assert len(po_case_ids) >= 7

    summary = run_eval_file(REPO_ROOT / "evals" / "eval_harness_seed_cases.json")
    assert summary.failed == 0
    assert summary.passed == summary.total


def _inventory_case() -> dict:
    return {
        "caseId": "fake-gateway-signature-probe",
        "utterance": "查物料 DEMOA1 在工厂 1000 的可用库存",
        "expectedCapabilityId": "MM.Inventory.GetAvailability",
    }


def test_fake_gateway_execute_accepts_approval_id_keyword():
    """FakeGatewayClient.execute must accept approval_id kw (matches GatewayClientProtocol)."""
    fake = FakeGatewayClient(_inventory_case())
    result = fake.execute(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA1", "plant": "1000"},
        approval_id="ap-write-001",
    )
    assert result.success is True
    # approval_id recorded for write-path tracing parity with real gateway
    assert fake.execute_calls[-1][0] == "MM.Inventory.GetAvailability"


def test_fake_gateway_execute_accepts_approval_id_positional():
    """FakeGatewayClient.execute must accept approval_id as 3rd positional arg."""
    fake = FakeGatewayClient(_inventory_case())
    result = fake.execute(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA1", "plant": "1000"},
        "ap-write-002",
    )
    assert result.success is True


def test_fake_gateway_execute_backward_compatible_without_approval_id():
    """Read path: calling execute without approval_id still works (default None)."""
    fake = FakeGatewayClient(_inventory_case())
    result = fake.execute(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA1", "plant": "1000"},
    )
    assert result.success is True
    assert len(fake.execute_calls) == 1


def test_fake_gateway_execute_signature_matches_gateway_client_protocol():
    """FakeGatewayClient.execute signature must match GatewayClientProtocol.execute."""
    import inspect

    from sap_nexus_agent.gateway_client import GatewayClientProtocol

    proto_params = list(inspect.signature(GatewayClientProtocol.execute).parameters.items())
    fake_params = list(inspect.signature(FakeGatewayClient.execute).parameters.items())

    assert [name for name, _ in proto_params] == [name for name, _ in fake_params]
    # approval_id must default to None for read-path backward compatibility
    fake_approval = fake_params[-1][1]
    assert fake_approval.default is None


# --- S2-A matcher Eval (Task 5) ---
#
# Design Doc §"测试策略" -> "S2-A matcher Eval": five MatchDecision classes
# (SELECT / CLARIFY / REJECT / SHOW_OPTIONS / ESCALATE_TO_PLANNER) plus a
# false-SELECT regression guard (D-1 fix: multi-goal utterance must NOT be
# silently reduced to SELECT).


def test_matcher_eval_file_passes():
    """matcher_cases.yaml runs end-to-end through run_query + select_capability
    and asserts the five-state MatchDecision per case."""
    summary = run_eval_file(REPO_ROOT / "evals" / "matcher_cases.yaml")

    # Five decision classes + false-SELECT regression; SHOW_OPTIONS is pending
    # (is_ambiguous not yet implemented in intent.py) so active count excludes it.
    assert summary.total >= 5
    assert summary.failed == 0
    assert summary.passed == summary.total


def test_matcher_eval_file_covers_five_decision_classes():
    """matcher_cases.yaml must include at least one case per decision class."""
    payload = json.loads(
        (REPO_ROOT / "evals" / "matcher_cases.yaml").read_text(encoding="utf-8")
    )
    decision_types = {
        case["expected"]["decisionType"]
        for case in payload["cases"]
        if "expected" in case
    }
    assert decision_types >= {
        "SELECT",
        "CLARIFY",
        "REJECT",
        "SHOW_OPTIONS",
        "ESCALATE_TO_PLANNER",
    }


def test_matcher_eval_file_has_false_select_regression_case():
    """A dedicated case must assert multi-goal utterance -> ESCALATE_TO_PLANNER
    (not SELECT). This is the D-1 regression guard."""
    payload = json.loads(
        (REPO_ROOT / "evals" / "matcher_cases.yaml").read_text(encoding="utf-8")
    )
    regression_cases = [
        case
        for case in payload["cases"]
        if case.get("id") == "false-select-regression"
    ]
    assert len(regression_cases) == 1
    case = regression_cases[0]
    assert case["expected"]["decisionType"] == "ESCALATE_TO_PLANNER"


def test_matcher_eval_catches_false_select_regression():
    """If a multi-goal utterance is silently reduced to SELECT, the matcher eval
    must report it as a 'false SELECT' regression failure.

    Constructs a synthetic case: a single-intent utterance (which the parser
    routes to SELECT) with an ESCALATE_TO_PLANNER expectation. The eval must
    raise AssertionError with the 'false SELECT' marker so a future regression
    is unmissable in CI output.
    """
    from sap_nexus_agent.eval import run_matcher_cases

    cases = [
        {
            "id": "false-select-probe",
            # Single-intent utterance -> real decision is SELECT.
            "userQuery": "DEMOA2 在 5100 还有多少可用库存",
            "expected": {
                "decisionType": "ESCALATE_TO_PLANNER",
                "validateCalls": 0,
                "executeCalls": 0,
            },
        }
    ]
    with pytest.raises(AssertionError) as exc_info:
        run_matcher_cases(cases)
    assert "false SELECT" in str(exc_info.value)


def test_matcher_eval_skips_pending_cases():
    """Cases marked pending=true are skipped (not failed), so SHOW_OPTIONS can
    stay documented in the eval file while is_ambiguous is unimplemented."""
    from sap_nexus_agent.eval import run_matcher_cases

    cases = [
        {
            "id": "pending-probe",
            "userQuery": "采购",
            "pending": True,
            "todo": "is_ambiguous not yet implemented",
            "expected": {
                "decisionType": "SHOW_OPTIONS",
                "validateCalls": 0,
                "executeCalls": 0,
            },
        }
    ]
    summary = run_matcher_cases(cases)
    assert summary.total == 0  # pending cases excluded from active total
    assert summary.failed == 0
    assert summary.passed == 0


def test_matcher_eval_routes_existing_files_through_legacy_path():
    """Auto-dispatch must not break existing eval files: inventory/PO/PR cases
    (which use expected.status, not expected.decisionType) still route through
    the legacy assertion path, not the matcher path."""
    # Existing files have no expected.decisionType; they must continue to pass.
    for filename in (
        "inventory_availability_cases.yaml",
        "eval_harness_seed_cases.json",
        "pr_create_cases.json",
        "purchase_order_cases.json",
    ):
        summary = run_eval_file(REPO_ROOT / "evals" / filename)
        assert summary.failed == 0
        assert summary.passed == summary.total


def test_governed_read_context_fixture_declares_complete_multi_turn_contract():
    """Each ordered Frame-v2 turn states its authority and Gateway boundary."""
    payload = json.loads(
        (REPO_ROOT / "evals" / "matcher_cases.yaml").read_text(encoding="utf-8")
    )
    context_cases = [case for case in payload["cases"] if case.get("fixtureVersion")]

    required = {
        "direct-plant-switch",
        "clear-then-ambiguous-reference",
        "explicit-correction",
        "llm-unavailable",
        "malformed-json",
        "technical-override-injection",
        "capability-switch",
        "recent-frame-explicit-restoration",
        "registry-drift",
        "principal-mismatch",
        "concurrent-turns",
        "duplicate-turn-id",
        "read-write-authority-isolation",
    }
    assert {case["id"] for case in context_cases} >= required
    for case in context_cases:
        assert case["fixtureVersion"] == "governed-read-context-v1"
        assert case["registrySnapshotId"]
        assert "initialContext" in case
        assert case["turns"]
        for turn in case["turns"]:
            assert turn["turnId"]
            assert turn["expected"]["frameStatus"]
            assert "slots" in turn["expected"]
            assert turn["expected"]["decision"]
            assert "validateDelta" in turn["expected"]
            assert "executeDelta" in turn["expected"]


def test_governed_read_context_eval_replays_reducer_and_enforces_turn_deltas():
    """A recorded bad model payload remains CLARIFY with no CallPlan or Gateway IO."""
    summary = run_eval_file(REPO_ROOT / "evals" / "matcher_cases.yaml")

    assert summary.failed == 0
    assert summary.passed == summary.total


# --- S2-B dry-run Eval (Task 9) ---


def test_dry_run_eval_file_passes():
    """dry_run_cases.yaml runs end-to-end through run_query + PlanCompiler
    and asserts the DryRunResult fields per case."""
    summary = run_eval_file(REPO_ROOT / "evals" / "dry_run_cases.yaml")

    # 3 active cases + 1 pending (missing-producer scenario cannot be
    # constructed with the real registry - all active capabilities have
    # produces_fact_types; covered by test_planner_plan_compiler unit tests).
    assert summary.total >= 3
    assert summary.failed == 0
    assert summary.passed == summary.total


def test_dry_run_eval_file_includes_multi_goal_case():
    """dry_run_cases.yaml must include the multi-goal case asserting
    nodeCount=2 (inventory + purchase_order) for an ESCALATE utterance."""
    payload = json.loads(
        (REPO_ROOT / "evals" / "dry_run_cases.yaml").read_text(encoding="utf-8")
    )
    multi_goal = [
        case for case in payload["cases"] if case.get("id") == "multi-goal-dry-run"
    ]
    assert len(multi_goal) == 1
    case = multi_goal[0]
    assert case["expected"]["decisionType"] == "ESCALATE_TO_PLANNER"
    assert case["expected"]["dryRun"]["nodeCount"] == 2


def test_dry_run_eval_catches_missing_dry_run_when_expected_present():
    """If expected.dryRun.present=True but outcome.dry_run is None, the eval
    must raise AssertionError. Constructs a synthetic case: a SELECT utterance
    (which produces no dry-run) with present=True."""
    from sap_nexus_agent.eval import run_matcher_cases

    cases = [
        {
            "id": "missing-dry-run-probe",
            "userQuery": "DEMOA2 在 5100 还有多少可用库存",  # -> SELECT
            "expected": {
                "decisionType": "SELECT",
                "validateCalls": 1,
                "executeCalls": 1,
                "dryRun": {"present": True},
            },
        }
    ]
    with pytest.raises(AssertionError) as exc_info:
        run_matcher_cases(cases)
    assert "dryRun.present=True but outcome.dry_run is None" in str(exc_info.value)


def test_dry_run_eval_catches_node_count_mismatch():
    """If expected.dryRun.nodeCount does not match the actual node count, the
    eval must raise AssertionError."""
    from sap_nexus_agent.eval import run_matcher_cases

    cases = [
        {
            "id": "node-count-mismatch-probe",
            "userQuery": "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单",
            "expected": {
                "decisionType": "ESCALATE_TO_PLANNER",
                "validateCalls": 0,
                "executeCalls": 0,
                "dryRun": {"nodeCount": 99},
            },
        }
    ]
    with pytest.raises(AssertionError) as exc_info:
        run_matcher_cases(cases)
    assert "dryRun.nodeCount mismatch" in str(exc_info.value)
