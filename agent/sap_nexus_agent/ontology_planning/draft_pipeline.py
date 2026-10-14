"""Shared draft acquisition: interpreter selection, precheck, validation, repair.

Used by both the Python coordinator and the TS planner mode so CLI and DSH
paths cannot diverge.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from .draft_validation import validate_draft
from .interpreter import FakeGoalInterpreter
from .release import PinnedRelease

NOT_RUN = ("SAP live", "paid model", "chat registration")

# Final validation code -> terminal status.
_FIELD_CODES = {"DRAFT_UNKNOWN_FIELD", "DRAFT_UNKNOWN_FACT_TYPE"}
_REJECT_CODES = {
    "DRAFT_SCHEMA_INVALID",
    "DRAFT_TECHNICAL_KEY",
    "DRAFT_BOUNDS",
    "DRAFT_DAG_CYCLE",
    "DRAFT_UNKNOWN_OPERATOR",
    "DRAFT_UNRESOLVED_INPUT",
}

InterpreterFactory = Callable[[Any], Any]


def live_model_authorized() -> bool:
    return os.environ.get("SAP_NEXUS_LLM_LIVE") == "1"


def _failure(status: str, reasons: list[str], pinned: PinnedRelease) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": status,
        "reasons": reasons,
        "writeGatewayCalls": 0,
        "releaseIds": {
            "semanticSnapshotId": pinned.package.semantic_snapshot_id,
            "registrySnapshotId": pinned.package.registry_snapshot_id,
        },
        "notRun": list(NOT_RUN),
    }


def _fact_gate_issues(document: dict[str, Any], pinned: PinnedRelease) -> list[tuple[str, str]]:
    # Unknown fact TYPES pass through: the resolver is the authority for
    # NO_PRODUCER (capability gap). Only illegal FIELDS of release-known facts
    # fail the draft (with one repair round for model drafts).
    issues: list[tuple[str, str]] = []
    for index, fact in enumerate(document.get("requestedFacts", [])):
        if not isinstance(fact, dict):
            continue
        fact_type = fact.get("factTypeId")
        allowed = pinned.allowlist_fields.get(fact_type)
        if allowed is None:
            continue
        for field in fact.get("fields", ()):
            if field not in allowed:
                issues.append((
                    "DRAFT_UNKNOWN_FIELD",
                    f"FIELD_NOT_ALLOWLISTED:{fact_type}.{field}",
                ))
    return issues


def _terminal_for_codes(codes: set[str], messages: list[str], pinned: PinnedRelease) -> dict[str, Any]:
    if codes & _FIELD_CODES:
        return _failure(
            "semantic_gap",
            [m for m in messages],
            pinned,
        )
    return _failure("rejected", messages, pinned)


def prepare_draft(
    request: dict[str, Any],
    sources: Any,
    pinned: PinnedRelease,
    fixtures_dir: Path,
    interpreter_instance: Any | None = None,
    live: bool | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (validated draft, terminal response). Exactly one is non-None."""
    if request.get("draftOverride") is not None:
        draft_document = request["draftOverride"]
    else:
        interpreter_name = request.get("interpreter", "fake")
        if interpreter_name == "model":
            authorized = live if live is not None else live_model_authorized()
            if not authorized:
                return None, _failure(
                    "rejected", ["MODEL_INTERPRETER_NOT_AUTHORIZED"], pinned
                )
            factory = _default_model_factory
            if interpreter_instance is None:
                interpreter_instance = factory(pinned)
        else:
            interpreter_instance = interpreter_instance or FakeGoalInterpreter(
                fixtures_dir / "drafts"
            )

        feedback = None
        draft_document = None
        for attempt in range(2):  # initial + one repair turn at most
            vocabulary = {
                "allowlist": pinned.allowlist_fields,
                "operators": pinned.operators,
            }
            draft_document = interpreter_instance.interpret(
                request, vocabulary, feedback=feedback
            )
            write_precheck = _precheck_write(draft_document, sources)
            if write_precheck:
                return None, _failure("rejected", [write_precheck], pinned)
            report = validate_draft(draft_document, pinned)
            fact_issues = _fact_gate_issues(draft_document, pinned)
            if report.valid and not fact_issues:
                return draft_document, None
            if attempt == 1 or interpreter_name != "model":
                break
            feedback = [
                {"path": issue.path, "code": issue.code, "message": issue.message}
                for issue in report.issues
            ] + [
                {"path": "$.requestedFacts", "code": code, "message": message}
                for code, message in fact_issues
            ]
        codes = {issue.code for issue in report.issues} | {code for code, _ in fact_issues}
        messages = [f"{issue.code}:{issue.message}" for issue in report.issues]
        # Fact-gate terminals use the resolver-compatible FIELD_NOT_ALLOWLISTED code.
        messages.extend(message for _code, message in fact_issues)
        return None, _terminal_for_codes(codes, messages, pinned)

    write_precheck = _precheck_write(draft_document, sources)
    if write_precheck:
        return None, _failure("rejected", [write_precheck], pinned)
    report = validate_draft(draft_document, pinned)
    fact_issues = _fact_gate_issues(draft_document, pinned)
    if not report.valid or fact_issues:
        codes = {issue.code for issue in report.issues} | {code for code, _ in fact_issues}
        messages = [f"{issue.code}:{issue.message}" for issue in report.issues]
        # Fact-gate terminals use the resolver-compatible FIELD_NOT_ALLOWLISTED code.
        messages.extend(message for _code, message in fact_issues)
        return None, _terminal_for_codes(codes, messages, pinned)
    return draft_document, None


def _registry_fact_producers(sources: Any, fact_type: str) -> list[dict[str, Any]]:
    return [
        capability
        for capability in sources.capabilities.get("capabilities", [])
        if any(
            output.get("factTypeRef") == fact_type
            for output in capability.get("outputs", [])
        )
    ]


def _precheck_write(draft_document: dict[str, Any], sources: Any) -> str | None:
    for fact in draft_document.get("requestedFacts", []):
        fact_type = fact.get("factTypeId")
        producers = _registry_fact_producers(sources, fact_type)
        if not producers:
            continue
        for producer in producers:
            governance = producer.get("governance", {})
            if (
                producer.get("kind") != "Function"
                or governance.get("sideEffect", "none") != "none"
                or governance.get("requiresApproval", False)
            ):
                return "WRITE_REJECTED"
    return None


def _default_model_factory(pinned: PinnedRelease) -> Any:
    from .model_interpreter import ModelGoalInterpreter

    return ModelGoalInterpreter(pinned)
