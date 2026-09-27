"""Deterministic root-cause attribution for bad-case candidates.

Five categories and a fixed rule order (architecture proposal Phase 2):
registry-alias / extraction / caliber / binding / governance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REGISTRY_ALIAS = "registry-alias"
EXTRACTION = "extraction"
CALIBER = "caliber"
BINDING = "binding"
GOVERNANCE = "governance"

CATEGORIES = (REGISTRY_ALIAS, EXTRACTION, CALIBER, BINDING, GOVERNANCE)

UNKNOWN_INTENT_TYPES = frozenset({"UNKNOWN_INTENT"})
BINDING_ERROR_TYPES = frozenset({
    "READ_EXECUTION_BINDING_MISMATCH",
    "SELECTION_EXECUTION_BINDING_MISMATCH",
    "BATCH_EXECUTION_BINDING_MISMATCH",
    "SOURCE_LOAD_ERROR",
    "SNAPSHOT_DRIFT",
    "SNAPSHOT_MISSING",
})


@dataclass(frozen=True)
class AttributionResult:
    category: str
    rationale: str
    evidence_refs: tuple[str, ...]
    patch_target: str | None
    secondary_signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "rationale": self.rationale,
            "evidenceRefs": list(self.evidence_refs),
            "patchTarget": self.patch_target,
            "secondarySignals": list(self.secondary_signals),
        }


def attribute_failure(
    observed: dict[str, Any], expected: dict[str, Any]
) -> AttributionResult:
    trace_id = str(observed.get("traceId"))
    actual_decision = observed.get("decision")
    expected_decision = expected.get("expectedDecision")
    actual_capability = observed.get("capabilityId")
    expected_capability = expected.get("expectedCapabilityId")
    error_type = observed.get("errorType")
    missing = observed.get("missingParameters") or []
    matched_capability = bool(
        expected_capability and actual_capability == expected_capability
    )

    # Rule 1: intent matched the right capability but a slot was not resolved.
    if expected_decision == "SELECT" and actual_decision == "CLARIFY" and matched_capability:
        return AttributionResult(
            EXTRACTION,
            f"intent matched {actual_capability} but parameter completion failed: {missing}",
            (trace_id,),
            f"registry/capabilities.yaml#{actual_capability}.inputs",
        )

    # Rule 2: intent never reached the expected capability.
    if (
        expected_decision == "SELECT"
        and actual_decision in {"CLARIFY", "REJECT"}
        and not matched_capability
        and error_type not in BINDING_ERROR_TYPES
    ):
        return AttributionResult(
            REGISTRY_ALIAS,
            f"intent did not match {expected_capability}; decision={actual_decision} errorType={error_type}",
            (trace_id,),
            f"registry/capabilities.yaml#{expected_capability}.aliases",
        )

    # Rule 3: right capability/decision but the business caliber was wrong.
    if (
        matched_capability
        and actual_decision == "SELECT"
        and expected.get("caliberMismatch")
    ):
        caliber_id = expected.get("expectedCaliberId")
        return AttributionResult(
            CALIBER,
            f"caliber mismatch; expectedCaliberId={caliber_id}",
            (trace_id,),
            f"ontology#{caliber_id}" if caliber_id else "ontology#definitions",
        )

    # Rule 5: any binding/source/snapshot failure surfaces as a binding issue.
    if error_type in BINDING_ERROR_TYPES:
        return AttributionResult(
            BINDING,
            f"errorType={error_type}",
            (trace_id,),
            "registry/executor-bindings.yaml",
        )

    # Rule 4: a request that should have been rejected was selected/executed.
    if expected_decision == "REJECT" and actual_decision == "SELECT":
        return AttributionResult(
            GOVERNANCE,
            "unsafe request was selected instead of being rejected",
            (trace_id,),
            None,
        )

    # Rule 6: unclassified.
    return AttributionResult(
        GOVERNANCE,
        f"no specific rule matched; actual={actual_decision} expected={expected_decision} errorType={error_type}",
        (trace_id,),
        None,
    )
