from __future__ import annotations

from dataclasses import dataclass
import json
from dataclasses import replace
from pathlib import Path
import sys
from typing import Any

from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.intent import parse_intent
from sap_nexus_agent.match_decision import MatchDecision
from sap_nexus_agent.orchestrator import continue_action, run_query


_CAPABILITY_TO_INTENT = {
    "MM.Inventory.GetAvailability": "inventory_availability",
    "MM.PurchaseOrder.GetList": "purchase_order_list",
}


@dataclass(frozen=True)
class EvalSummary:
    total: int
    passed: int
    failed: int


class FakeGatewayClient:
    def __init__(self, case: dict[str, Any]):
        gateway = case.get("gateway", {})
        case_id = _case_id(case)
        capability_id = case.get("expectedCapabilityId") or case.get("expected", {}).get("capabilityId")
        is_po = capability_id == "MM.PurchaseOrder.GetList"

        self.validation_payload = gateway.get(
            "validate",
            {
                "traceId": f"{case_id}-validate",
                "capabilityId": capability_id or "MM.Inventory.GetAvailability",
                "success": True,
                "errorType": "NONE",
                "messages": [],
            },
        )
        self.has_explicit_validation = "validate" in gateway
        if is_po:
            default_execute = {
                "traceId": f"{case_id}-execute",
                "capabilityId": "MM.PurchaseOrder.GetList",
                "success": True,
                "executor": {"type": "ODATA"},
                "returnMessages": [],
                "data": {
                    "purchaseOrders": [
                        {
                            "purchaseOrder": "4500000001",
                            "supplier": "DEMOV1",
                            "plant": "1000",
                            "material": "DEMOA1",
                            "orderQuantity": 100,
                            "purchaseOrderUnit": "EA",
                        },
                        {
                            "purchaseOrder": "4500000002",
                            "supplier": "DEMOV2",
                            "plant": "2000",
                            "material": "MAT-002",
                            "orderQuantity": 50,
                            "purchaseOrderUnit": "PC",
                        },
                    ],
                    "totalCount": 2,
                },
                "durationMs": 10,
                "errorType": "NONE",
            }
        else:
            default_execute = {
                "traceId": f"{case_id}-execute",
                "capabilityId": "MM.Inventory.GetAvailability",
                "success": True,
                "executor": {"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"},
                "returnMessages": [],
                "data": {
                    "availableQuantity": 12,
                    "unit": "EA",
                    "mrpElementLines": [
                        {
                            "mrpElementInd": "BE",
                            "mrpElement": "POitem",
                            "elementQty": 264,
                            "availQty1": 264,
                            "date": "2026-06-21",
                        },
                        {
                            "mrpElementInd": "WB",
                            "mrpElement": "Stock",
                            "elementQty": 12,
                            "availQty1": 12,
                            "date": "2026-06-21",
                        },
                    ],
                },
                "durationMs": 10,
                "errorType": "NONE",
            }
        self.execution_payload = gateway.get("execute", default_execute)
        self.validate_calls: list[tuple[str, dict[str, str]]] = []
        self.execute_calls: list[tuple[str, dict[str, str]]] = []

    def validate(self, capability_id: str, parameters: dict[str, str]) -> ValidationResult:
        self.validate_calls.append((capability_id, dict(parameters)))
        payload = self.validation_payload
        if not self.has_explicit_validation:
            payload = {**payload, "capabilityId": capability_id}
        return ValidationResult.from_dict(payload)

    def approve(self, capability_id: str, approval_record) -> str:
        # Task 18: registration channel echo; eval asserts on validate/execute counts only.
        return approval_record.approval_id

    def execute(
        self,
        capability_id: str,
        parameters: dict[str, str],
        approval_id: str | None = None,
        parameter_snapshot_hash: str | None = None,
        registry_snapshot_id: str | None = None,
        capability_version: str | None = None,
        approval_subject_hash: str | None = None,
    ) -> ExecutionResult:
        self.execute_calls.append((capability_id, dict(parameters)))
        return ExecutionResult.from_dict(self.execution_payload)


def run_eval_file(path: Path) -> EvalSummary:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["cases"]
    # S2-A matcher Eval auto-dispatch: cases assert on ``expected.decisionType``
    # (five-state MatchDecision) rather than ``expected.status`` (legacy
    # three-state). Routing is decided by the first case so the existing
    # inventory/PO/PR eval files keep using the legacy assertion path.
    if cases and "decisionType" in (cases[0].get("expected") or {}):
        recordings_path = path.parent / "recorded_llm" / "end_to_end_agent_release.json"
        recordings = (
            {
                str(recording["recordingId"]): recording
                for recording in json.loads(recordings_path.read_text(encoding="utf-8"))["recordings"]
            }
            if any(case.get("fixtureVersion") == "governed-read-context-v1" for case in cases)
            else None
        )
        return run_matcher_cases(cases, recordings)

    total = len(cases)
    failures: list[str] = []
    for case in cases:
        gateway = FakeGatewayClient(case)
        outcome = run_query(_case_utterance(case), gateway)
        expected = case.get("expected", {})
        if outcome.status == "awaiting_approval" and expected.get("executeCalls") == 1:
            outcome = continue_action(
                outcome.call_plan,
                outcome.validation_result,
                outcome.approval_record,
                gateway,
                decision="approve",
            )
        try:
            _assert_case(case, outcome, gateway)
        except AssertionError as exc:
            failures.append(f"{_case_id(case)}: {exc}")
    if failures:
        raise AssertionError("\n".join(failures))
    return EvalSummary(total=total, passed=total, failed=0)


def run_governed_context_evidence(path: Path) -> list[dict[str, Any]]:
    """Return observed production-boundary evidence for versioned context fixtures."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    recordings_path = path.parent / "recorded_llm" / "end_to_end_agent_release.json"
    recordings_payload = json.loads(recordings_path.read_text(encoding="utf-8"))
    recordings = {
        str(recording["recordingId"]): recording
        for recording in recordings_payload["recordings"]
    }
    evidence: list[dict[str, Any]] = []
    for case in payload["cases"]:
        if case.get("fixtureVersion") == "governed-read-context-v1":
            failure_context: dict[str, Any] = {
                "caseId": case.get("id", "unknown"),
                "turnId": None,
                "stage": "fixture_contract",
                "decision": None,
                "validateDelta": 0,
                "executeDelta": 0,
                "frame": None,
                "callPlan": None,
            }
            try:
                evidence.append(_run_governed_read_context_case(
                    case, recordings, failure_context=failure_context
                ))
            except AssertionError as exc:
                # Keep independent fixture evidence inspectable when one case
                # fails; release gates must not turn every case into "missing".
                evidence.append({
                    "caseId": case.get("id", "unknown"),
                    "fixtureVersion": case.get("fixtureVersion", "unknown"),
                    "registrySnapshotId": case.get("registrySnapshotId", ""),
                    "status": "failed",
                    "turns": [],
                    "failureRefs": [{
                        "caseId": case.get("id", "unknown"),
                        "turnId": failure_context["turnId"],
                        "stage": failure_context["stage"],
                        "decision": failure_context["decision"],
                        "validateDelta": failure_context["validateDelta"],
                        "executeDelta": failure_context["executeDelta"],
                        "frame": failure_context["frame"],
                        "callPlan": failure_context["callPlan"],
                        "message": str(exc) or "fixture assertion failed",
                    }],
                })
    return evidence


def run_matcher_cases(
    cases: list[dict[str, Any]],
    recordings: dict[str, dict[str, Any]] | None = None,
) -> EvalSummary:
    """S2-A matcher Eval (Design Doc §测试策略 -> S2-A matcher Eval).

    Routes each case through ``run_query`` (parse_intent + select_capability)
    and asserts ``outcome.match_decision.decision_type`` against
    ``expected.decisionType`` for the five decision classes:

    - SELECT            -> capabilityId + validateCalls=1 + executeCalls=1
    - CLARIFY           -> missingParameters + validateCalls=0 + executeCalls=0
    - REJECT            -> errorType + validateCalls=0 + executeCalls=0
    - SHOW_OPTIONS      -> pending (is_ambiguous not yet in intent.py)
    - ESCALATE_TO_PLANNER -> validateCalls=0 + executeCalls=0

    The ``false-select-regression`` case asserts a multi-goal utterance produces
    ESCALATE_TO_PLANNER (not SELECT); if the parser/selector regresses and
    returns SELECT, the failure is reported with the ``false SELECT`` marker so
    it is unmissable in CI output (D-1 fix guard).

    Cases marked ``pending: true`` are skipped (not failed) so SHOW_OPTIONS can
    stay documented in the eval file while ``is_ambiguous`` remains unimplemented
    in intent.py (Task 2 follow-up accepted by Task 3 review).
    """
    failures: list[str] = []
    skipped = 0
    passed = 0
    for case in cases:
        case_id = _case_id(case)
        if case.get("fixtureVersion") == "governed-read-context-v1":
            try:
                _run_governed_read_context_case(case, recordings)
            except AssertionError as exc:
                failures.append(f"{case_id}: {exc}")
            else:
                passed += 1
            continue
        if case.get("pending"):
            # SHOW_OPTIONS stays documented but skipped; is_ambiguous is a
            # Task 2 follow-up. The SHOW_OPTIONS branch in select_capability is
            # covered by agent/tests/test_capability_selector.py via a
            # SimpleNamespace double.
            todo = case.get("todo", "")
            print(f"SKIP (pending): {case_id}: {todo}", file=sys.stderr)
            skipped += 1
            continue

        gateway = FakeGatewayClient(case)
        outcome = run_query(_case_utterance(case), gateway)
        expected = case["expected"]
        decision = outcome.match_decision
        if decision is None:
            failures.append(f"{case_id}: outcome.match_decision is None")
            continue
        try:
            _assert_matcher_decision_type(case_id, decision, expected)
            _assert_matcher_state_fields(case_id, decision, expected)
            _assert_matcher_gateway_calls(case_id, gateway, expected)
            _assert_matcher_dry_run(case_id, outcome, expected)
        except AssertionError as exc:
            failures.append(str(exc))
        else:
            passed += 1

    if failures:
        raise AssertionError("\n".join(failures))
    return EvalSummary(total=passed, passed=passed, failed=0)


def _run_governed_read_context_case(
    case: dict[str, Any],
    recordings: dict[str, dict[str, Any]] | None = None,
    *,
    failure_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay versioned turns through the production Frame v2 resolver.

    The Eval harness owns only fixture assertions. It does not merge slots or
    synthesize decisions: all state changes come from ``resolve_read_turn`` and
    execution is the production ``continue_resolved_read`` path.
    """
    from sap_nexus_agent.conversation_context import ConversationContext
    from sap_nexus_agent.governed_context import PLACEHOLDER_PRINCIPAL, TrustedPrincipal
    from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal
    from sap_nexus_agent.workbench_output import outcome_to_workbench_dict
    from sap_nexus_agent.orchestrator import (
        _default_planner_sources,
        continue_resolved_read,
        resolve_read_turn,
    )
    from sap_nexus_agent.read_context import ConversationReadState

    _assert_context_fixture_contract(case)
    snapshot, sources = _default_planner_sources()
    initial_state = ConversationReadState.from_dict(case["initialContext"])
    context = ConversationContext(
        None,
        None,
        read_state=initial_state,
        schema_version=2,
    )
    gateway = FakeGatewayClient(case)
    observed_turns: list[dict[str, Any]] = []

    for turn in case["turns"]:
        if failure_context is not None:
            failure_context.update({
                "turnId": turn["turnId"],
                "stage": "resolve_read_turn",
                "decision": None,
                "validateDelta": 0,
                "executeDelta": 0,
                "frame": None,
                "callPlan": None,
            })
        candidate = turn["candidate"]
        expected = turn["expected"]
        capability_id = candidate["capabilityId"]
        recording_id = turn.get("recordingId")
        recording = recordings.get(recording_id) if recording_id and recordings else None
        if recording_id:
            assert recording is not None, f"unknown recording {recording_id}"
            assert recording.get("redacted") is True
            normalized = recording.get("normalizedResponse")
            assert isinstance(normalized, dict)
            assert normalized.get("capabilityId") == capability_id
            parameters = dict(normalized.get("parameters", {}))
        else:
            parameters = dict(candidate.get("parameters", {}))
        missing = list(candidate.get("missing", []))
        state_before = context.read_state.to_dict() if context.read_state else None
        if candidate.get("explicitRestore"):
            assert "回到刚才" in turn["userQuery"], "restore must be explicitly referenced"
            assert context.read_state is not None
            assert any(
                frame.capability_id == capability_id
                for frame in context.read_state.recent_frames
            ), "explicit restore target is not a recent Frame"

        def adapter(text: str, _context=None) -> IntentEnvelope:
            # Exercise the production advisory boundary for unavailable and
            # malformed recordings instead of attaching a fixture status to a
            # prebuilt successful envelope.
            if candidate.get("llmStatus") in {"unavailable", "malformed_json"}:
                from sap_nexus_agent.llm_client import LlmUnavailable
                from sap_nexus_agent.llm_intent import parse_with_hybrid
                from sap_nexus_agent.registry_loader import load_intent_catalog

                class BrokenAdvisoryClient:
                    def chat_json(self, *_args, **_kwargs):
                        if candidate["llmStatus"] == "unavailable":
                            raise LlmUnavailable("fixture unavailable")
                        raise json.JSONDecodeError("fixture malformed", "{", 0)

                return parse_with_hybrid(
                    text,
                    client=BrokenAdvisoryClient(),
                    catalog=load_intent_catalog(),
                )
            if candidate.get("technicalOverride"):
                from sap_nexus_agent.llm_intent import payload_to_envelope
                from sap_nexus_agent.registry_loader import load_intent_catalog

                catalog = load_intent_catalog()
                envelope = payload_to_envelope(
                    {
                        "capabilityId": "MM.PR.CreateDraft",
                        "parameters": {
                            "material": "DEMOA2",
                            "plant": "1000",
                            "rfcName": candidate["technicalOverride"],
                        },
                    },
                    catalog,
                    utterance=text,
                    snapshot_id="advisory-only",
                    visible_capability_ids=frozenset(
                        item.capability_id
                        for item in catalog.capabilities
                        if item.side_effect == "none"
                    ),
                )
                assert "technical_field:rfcName" in envelope.discard_reasons
                assert "unknown_capability:MM.PR.CreateDraft" in envelope.discard_reasons
                return envelope
            return IntentEnvelope(
                envelope_id=f"eval-{case['id']}-{turn['turnId']}",
                utterance=text,
                goals=(IntentGoal("fixture", capability_id, parameters, missing),),
                user_constraints={},
                ambiguities=[],
                reference_turn_id=None,
                model_evidence={
                    "fixtureStatus": candidate.get("llmStatus", "recorded"),
                    **dict(candidate.get("modelEvidence", {})),
                },
                snapshot_id="advisory-only",
                discard_reasons=[],
                created_by="fixture",
            )

        before_validate = len(gateway.validate_calls)
        before_execute = len(gateway.execute_calls)
        outcome = resolve_read_turn(
            turn["userQuery"],
            context=context,
            intent_adapter=adapter,
            principal=PLACEHOLDER_PRINCIPAL,
            snapshot=snapshot,
            sources=sources,
            turn_id=turn["turnId"],
        )
        assert outcome.match_decision is not None
        assert outcome.read_state is not None
        frame = outcome.read_state.active_frame
        if failure_context is not None:
            failure_context.update({
                "stage": "fixture_assertion",
                "decision": outcome.match_decision.decision_type,
                "validateDelta": len(gateway.validate_calls) - before_validate,
                "executeDelta": len(gateway.execute_calls) - before_execute,
                "frame": frame.to_dict() if frame is not None else {"status": "NONE"},
                "callPlan": (
                    {
                        "capabilityId": outcome.call_plan.capability_id,
                        "parameters": dict(outcome.call_plan.parameters),
                    }
                    if outcome.call_plan is not None else None
                ),
            })
        assert snapshot.snapshot_id == case["registrySnapshotId"], "fixture snapshot mismatch"
        assert outcome.match_decision.decision_type == expected["decision"], (
            f"decision mismatch: expected {expected['decision']}, "
            f"got {outcome.match_decision.decision_type}"
        )
        assert outcome.approval_record is None
        assert outcome.selection_execution_binding is None
        if expected["frameStatus"] is None:
            assert frame is None
            _assert_context_call_plan(outcome.call_plan, {}, expected["callPlan"])
        else:
            assert frame is not None
            assert frame.status == expected["frameStatus"]
            _assert_context_slots(frame.slots, expected["slots"])
            _assert_context_call_plan(outcome.call_plan, frame.slots, expected["callPlan"])
            _assert_context_frame_identity(outcome.read_state, expected)

        continuation = None
        if outcome.call_plan is not None:
            # Conflict fixtures exercise the real fail-closed continuation
            # preflight; normal READY turns exercise validate then execute.
            execution_principal = (
                TrustedPrincipal("fixture-other-principal", "operator", {"tenantId": "default"})
                if candidate.get("principalMismatch")
                else PLACEHOLDER_PRINCIPAL
            )
            current_snapshot = (
                replace(snapshot, snapshot_id=f"{snapshot.snapshot_id}-drift")
                if candidate.get("registryDrift")
                else snapshot
            )
            continued = continue_resolved_read(
                outcome.call_plan,
                outcome.read_execution_binding,
                gateway,
                persisted_state=outcome.read_state,
                principal=execution_principal,
                snapshot=current_snapshot,
                sources=sources,
            )
            continuation = {
                "status": continued.status,
                "errorType": continued.error_type,
                "workbenchOutcome": outcome_to_workbench_dict(continued),
            }

        validate_delta = len(gateway.validate_calls) - before_validate
        execute_delta = len(gateway.execute_calls) - before_execute
        if failure_context is not None:
            failure_context.update({
                "stage": "gateway_delta_assertion",
                "validateDelta": validate_delta,
                "executeDelta": execute_delta,
            })
        assert validate_delta == expected["validateDelta"]
        assert execute_delta == expected["executeDelta"]
        observed_turns.append({
            "turnId": turn["turnId"],
            "recordingId": recording_id,
            "stateBefore": state_before,
            "stateAfter": outcome.read_state.to_dict(),
            "frame": frame.to_dict() if frame is not None else {"status": "NONE"},
            "slots": {
                name: {
                    "value": slot.value,
                    "state": slot.state,
                    "role": slot.provenance,
                }
                for name, slot in (frame.slots.items() if frame is not None else ())
            },
            "decision": outcome.match_decision.decision_type,
            "callPlan": (
                {
                    "capabilityId": outcome.call_plan.capability_id,
                    "parameters": dict(outcome.call_plan.parameters),
                    "slotRoles": {
                        name: frame.slots[name].provenance
                        for name in outcome.call_plan.parameters
                        if name in frame.slots
                    },
                }
                if outcome.call_plan is not None
                else None
            ),
            "validateDelta": validate_delta,
            "executeDelta": execute_delta,
            "writeAuthority": {
                "approvalRecord": outcome.approval_record is not None,
                "selectionBinding": outcome.selection_execution_binding is not None,
            },
            "workbenchOutcome": outcome_to_workbench_dict(outcome),
            "continuation": continuation,
        })
        context = ConversationContext(
            None,
            None,
            read_state=outcome.read_state,
            schema_version=2,
        )
    return {
        "caseId": case["id"],
        "fixtureVersion": case["fixtureVersion"],
        "registrySnapshotId": snapshot.snapshot_id,
        "status": "passed",
        "turns": observed_turns,
        "failureRefs": [],
    }


def _assert_context_fixture_contract(case: dict[str, Any]) -> None:
    assert case.get("fixtureVersion") == "governed-read-context-v1"
    assert isinstance(case.get("registrySnapshotId"), str) and case["registrySnapshotId"]
    assert isinstance(case.get("initialContext"), dict)
    assert isinstance(case.get("turns"), list) and case["turns"]
    for turn in case["turns"]:
        assert isinstance(turn.get("turnId"), str) and turn["turnId"]
        expected = turn.get("expected")
        assert isinstance(expected, dict)
        assert expected.get("frameStatus") in {None, "COLLECTING", "READY", "CONFLICTED", "STALE"}
        assert isinstance(expected.get("slots"), dict)
        assert expected.get("decision") in {
            "SELECT", "CLARIFY", "REJECT", "SHOW_OPTIONS", "ESCALATE_TO_PLANNER"
        }
        assert isinstance(expected.get("validateDelta"), int)
        assert isinstance(expected.get("executeDelta"), int)
        assert "callPlan" in expected
        if "activeFrame" in expected:
            active = expected["activeFrame"]
            assert isinstance(active, dict)
            assert isinstance(active.get("capabilityId"), str) and active["capabilityId"]
            assert isinstance(active.get("frameId"), str) and active["frameId"]
            assert isinstance(expected.get("recentFrameCapabilityIds"), list)


def _assert_context_call_plan(actual: Any, slots: Any, expected: Any) -> None:
    if expected is None:
        assert actual is None, "unexpected CallPlan"
        return
    assert actual is not None, "missing expected CallPlan"
    assert actual.capability_id == expected["capabilityId"], "CallPlan capability mismatch"
    assert dict(actual.parameters) == expected["parameters"], "CallPlan parameters mismatch"
    assert {
        name: slots[name].provenance
        for name in actual.parameters
        if name in slots
    } == expected["slotRoles"], "CallPlan slot roles mismatch"


def _assert_context_frame_identity(state: ConversationReadState, expected: dict[str, Any]) -> None:
    identity = expected.get("activeFrame")
    if identity is None:
        return
    frame = state.active_frame
    assert frame is not None
    assert frame.capability_id == identity["capabilityId"], "active Frame capability mismatch"
    assert frame.frame_id == identity["frameId"], "active Frame identity mismatch"
    assert [frame.capability_id for frame in state.recent_frames] == expected[
        "recentFrameCapabilityIds"
    ], "recent Frame history mismatch"


def _assert_context_slots(actual: Any, expected: dict[str, Any]) -> None:
    assert set(actual) == set(expected), "unexpected Frame slots"
    for name, expected_slot in expected.items():
        assert name in actual, f"missing expected slot {name}"
        slot = actual[name]
        assert slot.value == expected_slot["value"], f"{name} value mismatch"
        role = expected_slot["role"]
        if role == "CLEARED":
            assert slot.state == "CLEARED", f"{name} expected CLEARED"
        else:
            assert slot.provenance == role, f"{name} role mismatch"


def _assert_matcher_decision_type(
    case_id: str, decision: MatchDecision, expected: dict[str, Any]
) -> None:
    actual = decision.decision_type
    expected_type = expected["decisionType"]
    if actual == expected_type:
        return
    # False-SELECT regression: multi-goal utterance silently reduced to SELECT
    # instead of ESCALATE_TO_PLANNER (D-1 fix guard). Called out explicitly so
    # a regression is unmissable in CI output.
    if expected_type == "ESCALATE_TO_PLANNER" and actual == "SELECT":
        raise AssertionError(
            f"{case_id}: false SELECT regression - expected ESCALATE_TO_PLANNER "
            f"but got SELECT (multi-goal utterance was silently reduced to a "
            f"single capability)"
        )
    raise AssertionError(
        f"{case_id}: decisionType mismatch - expected {expected_type}, got {actual}"
    )


def _assert_matcher_state_fields(
    case_id: str, decision: MatchDecision, expected: dict[str, Any]
) -> None:
    if "capabilityId" in expected and decision.capability_id != expected["capabilityId"]:
        raise AssertionError(
            f"{case_id}: capabilityId mismatch - expected {expected['capabilityId']}, "
            f"got {decision.capability_id}"
        )
    if "missingParameters" in expected and decision.missing_parameters != expected["missingParameters"]:
        raise AssertionError(
            f"{case_id}: missingParameters mismatch - expected {expected['missingParameters']}, "
            f"got {decision.missing_parameters}"
        )
    if "errorType" in expected and decision.error_type != expected["errorType"]:
        raise AssertionError(
            f"{case_id}: errorType mismatch - expected {expected['errorType']}, "
            f"got {decision.error_type}"
        )


def _assert_matcher_gateway_calls(
    case_id: str, gateway: FakeGatewayClient, expected: dict[str, Any]
) -> None:
    expected_validate = expected.get("validateCalls", 0)
    expected_execute = expected.get("executeCalls", 0)
    if len(gateway.validate_calls) != expected_validate:
        raise AssertionError(
            f"{case_id}: validateCalls mismatch - expected {expected_validate}, "
            f"got {len(gateway.validate_calls)}"
        )
    if len(gateway.execute_calls) != expected_execute:
        raise AssertionError(
            f"{case_id}: executeCalls mismatch - expected {expected_execute}, "
            f"got {len(gateway.execute_calls)}"
        )


def _assert_matcher_dry_run(case_id: str, outcome: Any, expected: dict[str, Any]) -> None:
    """S2-B dry-run eval assertions (Design Doc §测试策略 -> S2-B dry-run cases).

    Optional ``expected.dryRun`` block asserts on the ``DryRunResult``
    carried by ESCALATE_TO_PLANNER outcomes. When absent, no dry-run
    assertion is made (backward compat with matcher_cases.yaml).

    Supported fields:
    - ``present`` (bool): assert ``outcome.dry_run`` is/not None.
    - ``nodeCount`` (int): assert ``len(plan_graph["nodes"])`` equals.
    - ``nodeCapabilities`` (list[str]): assert the set of node capabilityIds
      matches (order-independent).
    - ``gapsContain`` (str): assert any gap.kind or gap.detail contains the
      substring (e.g. ``"missing_capability"``).
    - ``flagsContain`` (str): assert any flag.kind or flag.detail contains
      the substring.
    - ``rationaleNonEmpty`` (bool): assert ``rationale`` is a non-empty str.
    """
    dry_run_expected = expected.get("dryRun")
    if dry_run_expected is None:
        return
    dry_run = outcome.dry_run
    if dry_run_expected.get("present") is False:
        if dry_run is not None:
            raise AssertionError(
                f"{case_id}: dryRun.present=False but outcome.dry_run is not None"
            )
        return
    if dry_run_expected.get("present") is True and dry_run is None:
        raise AssertionError(
            f"{case_id}: dryRun.present=True but outcome.dry_run is None"
        )
    if dry_run is None:
        # No further assertions possible; caller did not require present=True.
        return
    plan_graph = dry_run.plan_graph
    if "nodeCount" in dry_run_expected:
        actual = len(plan_graph.get("nodes", []))
        if actual != dry_run_expected["nodeCount"]:
            raise AssertionError(
                f"{case_id}: dryRun.nodeCount mismatch - expected "
                f"{dry_run_expected['nodeCount']}, got {actual}"
            )
    if "nodeCapabilities" in dry_run_expected:
        actual = {n.get("capabilityId") for n in plan_graph.get("nodes", [])}
        expected_set = set(dry_run_expected["nodeCapabilities"])
        if actual != expected_set:
            raise AssertionError(
                f"{case_id}: dryRun.nodeCapabilities mismatch - expected "
                f"{sorted(expected_set)}, got {sorted(actual)}"
            )
    if "gapsContain" in dry_run_expected:
        needle = dry_run_expected["gapsContain"]
        if not any(
            needle in gap.kind or needle in gap.detail for gap in dry_run.gaps
        ):
            raise AssertionError(
                f"{case_id}: dryRun.gapsContain '{needle}' not found in gaps"
            )
    if "flagsContain" in dry_run_expected:
        needle = dry_run_expected["flagsContain"]
        if not any(
            needle in flag.kind or needle in flag.detail
            for flag in dry_run.governance_flags
        ):
            raise AssertionError(
                f"{case_id}: dryRun.flagsContain '{needle}' not found in flags"
            )
    if dry_run_expected.get("rationaleNonEmpty"):
        if not isinstance(dry_run.rationale, str) or not dry_run.rationale:
            raise AssertionError(
                f"{case_id}: dryRun.rationaleNonEmpty=True but rationale is empty"
            )
    _assert_parameter_provenance(case_id, plan_graph, dry_run_expected)
    _assert_data_edge_fact_types(case_id, plan_graph, dry_run_expected)
    _assert_ordered_before(case_id, plan_graph, dry_run_expected)


# T5 task 7.1: the vocabulary the spec delta requires. `capability_derived` is an
# eval-harness term, not a runtime enum (correction C12): the runtime carries the
# provenance as the binding's own discriminant, so the mapping is defined here,
# once, and every case reads through it.
_PROVENANCE_BY_SOURCE_KIND = {
    "factField": "capability_derived",
    "literal": "user_supplied",
    "goalConstraint": "goal_constraint",
    "registeredDefault": "registered_default",
}


def _bindings_by_capability(plan_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        node.get("capabilityId"): {
            binding["parameterName"]: binding["source"]
            for binding in node.get("parameterBindings", [])
        }
        for node in plan_graph.get("nodes", [])
    }


def _assert_parameter_provenance(
    case_id: str, plan_graph: dict[str, Any], expected: dict[str, Any]
) -> None:
    """``parameterProvenance``: {capabilityId: {parameter: provenance}}.

    A parameter absent from the plan's bindings is reported as ``not_bound``
    rather than omitted, so "the field was not elicited" and "the field silently
    vanished" cannot produce the same green result. Asserted as an exact dict per
    capability, so an extra derived parameter fails too.
    """
    wanted = expected.get("parameterProvenance")
    if wanted is None:
        return
    bindings = _bindings_by_capability(plan_graph)
    for capability_id, parameters in wanted.items():
        node_bindings = bindings.get(capability_id)
        if node_bindings is None:
            raise AssertionError(
                f"{case_id}: parameterProvenance names {capability_id}, which is "
                f"not a node in the plan"
            )
        actual = {
            name: _PROVENANCE_BY_SOURCE_KIND.get(
                node_bindings[name].get("kind"), node_bindings[name].get("kind")
            )
            if name in node_bindings
            else "not_bound"
            for name in parameters
        }
        if actual != parameters:
            raise AssertionError(
                f"{case_id}: parameterProvenance mismatch for {capability_id} - "
                f"expected {parameters}, got {actual}"
            )


def _assert_data_edge_fact_types(
    case_id: str, plan_graph: dict[str, Any], expected: dict[str, Any]
) -> None:
    """``dataEdges``: the exact list of ``(from, to, factTypeId)`` triples.

    A list, not a set, and exact: task 5.5's defect was a *duplicate* edge for one
    triple, so a containment check would have passed straight through it.
    """
    wanted = expected.get("dataEdges")
    if wanted is None:
        return
    actual = [
        [edge.get("fromNodeId"), edge.get("toNodeId"), edge.get("factTypeId")]
        for edge in plan_graph.get("edges", [])
        if edge.get("kind") == "data"
    ]
    if actual != [list(item) for item in wanted]:
        raise AssertionError(
            f"{case_id}: dataEdges mismatch - expected {wanted}, got {actual}"
        )


def _assert_ordered_before(
    case_id: str, plan_graph: dict[str, Any], expected: dict[str, Any]
) -> None:
    """``orderedBefore``: [[earlier, later], ...] against ``topologicalOrder``.

    Both node ids must be present; a missing one is an error rather than a
    vacuous pass, which is the failure mode a plain index comparison invites.
    """
    wanted = expected.get("orderedBefore")
    if wanted is None:
        return
    order = list(plan_graph.get("topologicalOrder", []))
    for earlier, later in wanted:
        if earlier not in order or later not in order:
            raise AssertionError(
                f"{case_id}: orderedBefore names {earlier!r}/{later!r} but "
                f"topologicalOrder is {order}"
            )
        if order.index(earlier) >= order.index(later):
            raise AssertionError(
                f"{case_id}: orderedBefore violated - {earlier} must precede "
                f"{later} in {order}"
            )


def _assert_case(case: dict[str, Any], outcome: Any, gateway: FakeGatewayClient) -> None:
    if "expectedDecision" in case:
        _assert_seed_case(case, outcome, gateway)
        return

    expected = case["expected"]
    assert outcome.status == expected["status"]
    if "capabilityId" in expected:
        assert outcome.call_plan is not None
        assert outcome.call_plan.capability_id == expected["capabilityId"]
    if "missingParameters" in expected:
        assert outcome.missing_parameters == expected["missingParameters"]
    if "errorType" in expected:
        assert outcome.error_type == expected["errorType"]
    if "responseContains" in expected:
        response = outcome.response_text or ""
        for text in expected["responseContains"]:
            assert text in response
    for text in expected.get("sensitiveAbsent", []):
        assert text not in (outcome.response_text or "")
    assert len(gateway.validate_calls) == expected["validateCalls"]
    assert len(gateway.execute_calls) == expected["executeCalls"]


def _assert_seed_case(case: dict[str, Any], outcome: Any, gateway: FakeGatewayClient) -> None:
    _assert_seed_contract_shape(case)
    expected_status = {
        "SELECT": "success",
        "CLARIFY": "clarification",
        "REJECT": "failure",
    }[case["expectedDecision"]]
    assert outcome.status == expected_status

    if case.get("expectedCapabilityId"):
        if outcome.call_plan is not None:
            assert outcome.call_plan.capability_id == case["expectedCapabilityId"]
        else:
            parsed = parse_intent(case["utterance"])
            expected_intent = _CAPABILITY_TO_INTENT.get(case["expectedCapabilityId"])
            if expected_intent:
                assert parsed.intent == expected_intent

    if "expectedParameters" in case:
        actual_parameters = _actual_parameters(case, outcome)
        for name, value in case["expectedParameters"].items():
            assert actual_parameters.get(name) == value

    clarification = case.get("expectedClarification")
    if clarification:
        assert outcome.missing_parameters == clarification["missingFields"]
        _assert_clarification_intent(clarification["questionIntent"], outcome.response_text or "")

    if case.get("expectedRejectReason") is not None:
        assert outcome.error_type == case["expectedRejectReason"]

    business_caliber = case.get("expectedBusinessCaliber")
    if business_caliber and case["expectedDecision"] == "SELECT":
        _assert_business_caliber(business_caliber["caliberId"], outcome)

    response = outcome.response_text or ""
    for text in case.get("responseContains", []):
        assert text in response
    for text in case.get("sensitiveAbsent", []):
        assert text not in response

    expected_calls = _expected_gateway_calls(case["expectedDecision"])
    assert len(gateway.validate_calls) == expected_calls[0]
    assert len(gateway.execute_calls) == expected_calls[1]


def _assert_seed_contract_shape(case: dict[str, Any]) -> None:
    assert case["caseId"]
    assert case["status"] == "active"
    assert case["utterance"]
    assert case["expectedDecision"] in {"SELECT", "CLARIFY", "REJECT"}
    assert isinstance(case["regressionTags"], list)
    assert case["regressionTags"]
    assert "createdAt" in case


def _actual_parameters(case: dict[str, Any], outcome: Any) -> dict[str, str]:
    if outcome.call_plan is not None:
        return outcome.call_plan.parameters
    return parse_intent(case["utterance"]).parameters


def _assert_clarification_intent(question_intent: str, response: str) -> None:
    expected_text = {
        "ask_for_material": "物料",
        "ask_for_plant": "工厂",
        "ask_for_filter": "过滤条件",
    }[question_intent]
    assert expected_text in response


def _assert_business_caliber(caliber_id: str, outcome: Any) -> None:
    if caliber_id == "MM.PurchaseOrder.ListQuery.v1":
        assert outcome.facts is not None
        if outcome.facts:
            assert outcome.facts[0].domain == "MM"
            assert outcome.facts[0].business_object == "PurchaseOrder"
            assert outcome.facts[0].predicate == "purchaseOrderItem"
        return
    assert caliber_id == "MM.Inventory.AvailabilityForCommitment.v1"
    assert outcome.fact is not None
    assert outcome.fact.domain == "MM"
    assert outcome.fact.business_object == "InventoryStock"
    assert outcome.fact.predicate == "availableQuantity"


def _expected_gateway_calls(decision: str) -> tuple[int, int]:
    if decision == "SELECT":
        return (1, 1)
    return (0, 0)


def _case_id(case: dict[str, Any]) -> str:
    return str(case.get("caseId") or case.get("id"))


def _case_utterance(case: dict[str, Any]) -> str:
    return str(case.get("utterance") or case.get("userQuery"))


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) not in {1, 2} or (len(args) == 2 and args[1] != "--context-evidence"):
        print(
            "Usage: python -m sap_nexus_agent.eval <json-formatted-cases-file> [--context-evidence]",
            file=sys.stderr,
        )
        return 2
    if len(args) == 2:
        print(json.dumps({"cases": run_governed_context_evidence(Path(args[0]))}, ensure_ascii=False))
        return 0
    summary = run_eval_file(Path(args[0]))
    print(f"Eval passed: {summary.passed}/{summary.total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
