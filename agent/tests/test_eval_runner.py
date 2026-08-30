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
        "sales_order_list_cases.yaml",
        "ar_open_items_cases.yaml",
        "ap_open_items_cases.yaml",
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
            assert "frameStatus" in turn["expected"]
            assert "slots" in turn["expected"]
            assert turn["expected"]["decision"]
            assert "validateDelta" in turn["expected"]
            assert "executeDelta" in turn["expected"]
            assert "callPlan" in turn["expected"]


def test_governed_read_context_eval_replays_reducer_and_enforces_turn_deltas():
    """A recorded bad model payload remains CLARIFY with no CallPlan or Gateway IO."""
    summary = run_eval_file(REPO_ROOT / "evals" / "matcher_cases.yaml")

    assert summary.failed == 0
    assert summary.passed == summary.total


def test_governed_context_evidence_uses_recorded_bad_payload_and_observes_each_turn():
    """Release metrics must consume resolver observations, not fixture labels."""
    from sap_nexus_agent.eval import run_governed_context_evidence

    evidence = run_governed_context_evidence(REPO_ROOT / "evals" / "matcher_cases.yaml")
    bad = next(case for case in evidence if case["caseId"] == "clear-then-ambiguous-reference")
    turn = bad["turns"][-1]

    assert turn["recordingId"] == "recording-context-bad"
    assert turn["decision"] == "CLARIFY"
    assert turn["callPlan"] is None
    assert turn["validateDelta"] == 0
    assert turn["executeDelta"] == 0
    assert turn["slots"]["material"]["state"] != "RESOLVED"
    assert turn["slots"]["plant"]["value"] == "1000"
    assert turn["writeAuthority"] == {"approvalRecord": False, "selectionBinding": False}


def test_recent_frame_restoration_requires_explicit_capability_round_trip():
    """The fixture must prove a real switch before explicitly returning to inventory."""
    from sap_nexus_agent.eval import run_governed_context_evidence

    evidence = run_governed_context_evidence(REPO_ROOT / "evals" / "matcher_cases.yaml")
    restored = next(case for case in evidence if case["caseId"] == "recent-frame-explicit-restoration")

    assert [turn["decision"] for turn in restored["turns"]] == ["SELECT", "SELECT", "CLARIFY"]
    switch = restored["turns"][1]
    final = restored["turns"][2]
    assert switch["stateAfter"]["activeFrame"]["capabilityId"] == "MM.PurchaseOrder.GetList"
    assert switch["stateAfter"]["recentFrames"][0]["capabilityId"] == "MM.Inventory.GetAvailability"
    assert final["stateAfter"]["activeFrame"]["capabilityId"] == "MM.Inventory.GetAvailability"
    assert final["stateAfter"]["activeFrame"]["frameId"] == "MM.Inventory.GetAvailability:restore-3"
    assert final["stateAfter"]["recentFrames"][0]["capabilityId"] == "MM.PurchaseOrder.GetList"
    assert final["callPlan"] is None
    assert final["validateDelta"] == 0
    assert final["executeDelta"] == 0


def test_governed_context_evidence_preserves_case_results_and_production_outcomes():
    """Release gates need every case result, including immutable resolver evidence."""
    from sap_nexus_agent.eval import run_governed_context_evidence

    evidence = run_governed_context_evidence(REPO_ROOT / "evals" / "matcher_cases.yaml")

    assert len(evidence) == 13
    assert all(case["status"] == "passed" for case in evidence)
    seeded = next(case for case in evidence if case["caseId"] == "clear-then-ambiguous-reference")
    assert seeded["turns"][0]["stateBefore"]["stateVersion"] == 4
    assert set(seeded["turns"][0]["stateBefore"]["activeFrame"]["slots"]) == {"material", "plant"}
    selected = next(case for case in evidence if case["caseId"] == "direct-plant-switch")
    turn = selected["turns"][0]
    assert turn["workbenchOutcome"]["callPlan"] == {
        "agentTraceId": turn["workbenchOutcome"]["callPlan"]["agentTraceId"],
        "capabilityId": "MM.Inventory.GetAvailability",
        "kind": "Function",
        "parameters": {"material": "DEMOA2", "plant": "5100", "unit": "EA"},
        "validationPolicy": "validate_before_execute",
        "createdBy": "agent",
        "requiresApproval": False,
    }
    assert turn["workbenchOutcome"]["readExecutionBinding"]["readState"] == turn["stateAfter"]
    assert turn["continuation"]["status"] == "success"
    assert turn["continuation"]["errorType"] is None
    assert turn["continuation"]["workbenchOutcome"]["status"] == "success"
    assert selected["failureRefs"] == []

    for case_id in ("llm-unavailable", "malformed-json"):
        fallback = next(case for case in evidence if case["caseId"] == case_id)["turns"][0]
        assert fallback["decision"] == "CLARIFY"
        assert fallback["callPlan"] is None
        assert fallback["validateDelta"] == 0
        assert fallback["executeDelta"] == 0

    override = next(case for case in evidence if case["caseId"] == "technical-override-injection")["turns"][0]
    assert override["decision"] == "REJECT"
    assert override["workbenchOutcome"]["errorType"] == "UNSUPPORTED_RFC_NAME"
    assert override["callPlan"] is None
    assert override["writeAuthority"] == {"approvalRecord": False, "selectionBinding": False}


def test_governed_context_failure_ref_tracks_the_failing_turn_and_observations(tmp_path):
    from sap_nexus_agent.eval import run_governed_context_evidence

    fixtures = json.loads((REPO_ROOT / "evals" / "matcher_cases.yaml").read_text("utf-8"))
    case = next(item for item in fixtures["cases"] if item["id"] == "clear-then-ambiguous-reference")
    case["turns"][2]["expected"]["decision"] = "SELECT"
    evals_dir = tmp_path / "evals"
    recordings_dir = evals_dir / "recorded_llm"
    recordings_dir.mkdir(parents=True)
    fixture_path = evals_dir / "matcher_cases.yaml"
    fixture_path.write_text(json.dumps(fixtures), encoding="utf-8")
    (recordings_dir / "end_to_end_agent_release.json").write_text(
        (REPO_ROOT / "evals" / "recorded_llm" / "end_to_end_agent_release.json").read_text("utf-8"),
        encoding="utf-8",
    )

    evidence = run_governed_context_evidence(fixture_path)

    assert len(evidence) == 13
    assert next(case for case in evidence if case["caseId"] == "direct-plant-switch")["status"] == "passed"
    failed = next(case for case in evidence if case["caseId"] == "clear-then-ambiguous-reference")
    assert failed["status"] == "failed"
    assert len(failed["failureRefs"]) == 1
    ref = failed["failureRefs"][0]
    assert {key: ref[key] for key in (
        "caseId", "turnId", "stage", "decision", "validateDelta",
        "executeDelta", "callPlan", "message",
    )} == {
        "caseId": "clear-then-ambiguous-reference",
        "turnId": "clear-3",
        "stage": "fixture_assertion",
        "decision": "CLARIFY",
        "validateDelta": 0,
        "executeDelta": 0,
        "callPlan": None,
        "message": "decision mismatch: expected SELECT, got CLARIFY",
    }
    frame = ref["frame"]
    assert frame["status"] == "COLLECTING"
    assert set(frame["slots"]) == {"material", "plant"}


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


# --- S3 derived-parameter Eval (T2 task 4.1) ---


DERIVED_PARAMETER_CASE_IDS = (
    "derived-not-asked",
    "user-supplied-wins",
    "derived-and-user-supplied-mixed",
    "upstream-empty-degrades-to-elicitation",
    "upstream-unreachable-emits-capability-gap",
)

#: Keys the harness reads from ``expected``, kept in sync with the assertion
#: functions at ``eval.py:634-760``. Any key the file carries that is NOT in
#: this set would be silently ignored -- so the test below locks every present
#: key against this set.
HARNESS_ASSERTED_KEYS = frozenset(
    {
        "decisionType",
        "capabilityId",
        "missingParameters",
        "errorType",
        "validateCalls",
        "executeCalls",
        "dryRun",
    }
)

# T5 task 7.5 added a case-level key that restricts the governed capability set.
# Listed separately from the `expected` keys because it is an *input*, not an
# assertion: it changes which registry state the case runs against.
HARNESS_CASE_LEVEL_KEYS = frozenset({"governedCapabilities"})


DERIVED_PARAMETER_LIVE_CASE_IDS = frozenset(
    {
        "user-supplied-wins",
        "derived-and-user-supplied-mixed",
        "upstream-unreachable-emits-capability-gap",
    }
)


def test_derived_parameter_cases_exist_and_are_live_or_attributed():
    """Five stable case ids; T5 task 7.1 turned two of them live.

    Before 7.1 every case was `pending` and this test pinned that. It now pins
    the stronger property the spec delta actually requires: a case is either
    **live** or **pending with an attribution long enough to name its cause**,
    and it may never be silently dropped or left pending without one. The two
    live ids are named explicitly, so a live case regressing to `pending` fails
    here instead of quietly reducing coverage.
    """
    payload = json.loads(
        (REPO_ROOT / "evals" / "derived_parameter_cases.yaml").read_text(
            encoding="utf-8"
        )
    )
    ids = [case.get("id") for case in payload["cases"]]

    for case_id in DERIVED_PARAMETER_CASE_IDS:
        assert case_id in ids, f"missing case id: {case_id}"

    live = {c.get("id") for c in payload["cases"] if not c.get("pending")}
    assert live == set(DERIVED_PARAMETER_LIVE_CASE_IDS), (
        f"live case set changed: expected {sorted(DERIVED_PARAMETER_LIVE_CASE_IDS)}, "
        f"got {sorted(live)}"
    )

    for case in payload["cases"]:
        if not case.get("pending"):
            # A live case must not keep a `todo`: leaving one behind is how a
            # case that already passes goes on reading as unfinished work.
            assert "todo" not in case, f"{case.get('id')}: live case still has a todo"
            continue
        todo = case.get("todo", "")
        assert isinstance(todo, str) and len(todo) > 20, (
            f"{case.get('id')}: todo is empty or too short"
        )
        expected = case.get("expected", {})
        unknown = set(expected.keys()) - HARNESS_ASSERTED_KEYS
        assert not unknown, (
            f"{case.get('id')}: expected keys not asserted by harness: {unknown}"
        )


def test_the_eval_summary_counts_pending_cases_as_unresolved():
    """R2 — the spec clause "counted as unresolved rather than ... silently omitted".

    Before this the summary carried only total/passed/failed, so a suite with
    three live and two pending cases reported `Eval passed: 3/3` and the two
    unresolved cases appeared only as stderr lines. "Not counted as passed" was
    satisfied; "counted as unresolved" was not.
    """
    payload = json.loads(
        (REPO_ROOT / "evals" / "derived_parameter_cases.yaml").read_text(
            encoding="utf-8"
        )
    )
    expected_pending = sum(1 for case in payload["cases"] if case.get("pending"))
    assert expected_pending > 0  # non-vacuity: there is something to count

    summary = run_eval_file(REPO_ROOT / "evals" / "derived_parameter_cases.yaml")

    assert summary.unresolved == expected_pending
    assert summary.passed == len(DERIVED_PARAMETER_LIVE_CASE_IDS)
    assert summary.failed == 0


def test_derived_parameter_eval_counts_only_the_live_cases():
    """Two live cases pass; the three pending ones are neither passed nor failed.

    Before T5 task 7.1 this asserted 0/0. The counts must equal the live-case
    count exactly -- reporting 5/5 would mean a pending case was counted as
    passing, which is the specific thing the spec delta's
    "eval evidence reports pending cases as unresolved" requirement forbids.
    """
    summary = run_eval_file(
        REPO_ROOT / "evals" / "derived_parameter_cases.yaml"
    )
    assert summary.total == len(DERIVED_PARAMETER_LIVE_CASE_IDS)
    assert summary.passed == len(DERIVED_PARAMETER_LIVE_CASE_IDS)
    assert summary.failed == 0


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
