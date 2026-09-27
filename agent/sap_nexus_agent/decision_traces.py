"""Append-only decision trace recording (offline-loop input).

Records one redacted JSONL line per agent turn. Raw utterances are never
stored; traces default to the gitignored ``runtime/traces/`` directory.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

FORBIDDEN_PARAMETER_KEYS = frozenset({
    "credential", "credentials", "password", "token", "apikey", "key",
    "secret", "url", "sql", "rawresponse", "rawsappayload",
})

_DISABLED_VALUES = frozenset({"", "0", "off", "false", "no"})
_STATUS_DECISION = {
    "success": "SELECT",
    "clarification": "CLARIFY",
    "failure": "REJECT",
    "awaiting_approval": "SELECT",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    # decision_traces.py -> sap_nexus_agent -> agent -> repo root
    return Path(__file__).resolve().parents[2]


def resolve_trace_path() -> Path | None:
    """Resolve the trace file path from env or the default; None when disabled."""
    raw = os.environ.get(
        "SAP_NEXUS_DECISION_TRACE",
        str(_repo_root() / "runtime/traces/decisions.jsonl"),
    )
    if raw.strip().lower() in _DISABLED_VALUES:
        return None
    return Path(raw).expanduser()


class DecisionTraceStore:
    def __init__(self, path: Path, *, now: Callable[[], str] = _utc_now):
        self._path = path
        self._now = now

    def append(self, record: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def write_turn(self, record: dict[str, Any]) -> None:
        self.append(record)


def _decision_from_outcome(outcome: Any) -> str | None:
    match = getattr(outcome, "match_decision", None)
    if match is not None and getattr(match, "decision_type", None):
        return str(match.decision_type)
    status = getattr(outcome, "status", None)
    if status in _STATUS_DECISION:
        return _STATUS_DECISION[status]
    if status:
        return str(status)
    return None


def _filter_parameters(parameters: dict[str, Any] | None) -> dict[str, str]:
    if not parameters:
        return {}
    return {
        str(key): str(value)
        for key, value in parameters.items()
        if str(key).lower() not in FORBIDDEN_PARAMETER_KEYS
    }


def _slot_roles(outcome: Any) -> dict[str, str] | None:
    read_state = getattr(outcome, "read_state", None)
    slots = getattr(read_state, "slots", None)
    if not isinstance(slots, dict) or not slots:
        return None
    roles = {}
    for name, slot in slots.items():
        role = getattr(slot, "role", None)
        if role:
            roles[str(name)] = str(role)
    return roles or None


def _model_label(intent_adapter: Callable[..., Any] | None) -> str:
    if intent_adapter is None:
        return "rule"
    name = getattr(intent_adapter, "__name__", "").lower()
    explicit = getattr(intent_adapter, "model", None) or getattr(
        intent_adapter, "model_id", None
    )
    if explicit:
        return str(explicit)
    if "llm" in name:
        return "llm"
    return "rule"


def _user_correction(outcome: Any) -> bool:
    read_state = getattr(outcome, "read_state", None)
    frame = getattr(read_state, "active_frame", None)
    previous_capability = getattr(frame, "capability_id", None)
    current = getattr(outcome, "call_plan", None)
    current_capability = getattr(current, "capability_id", None)
    return bool(previous_capability and current_capability
                and previous_capability != current_capability)


def build_decision_record(
    utterance: str,
    outcome: Any,
    *,
    intent_adapter: Callable[..., Any] | None = None,
    trace_id: str | None = None,
    now: Callable[[], str] = _utc_now,
) -> dict[str, Any]:
    decision = _decision_from_outcome(outcome)
    call_plan = getattr(outcome, "call_plan", None)
    match = getattr(outcome, "match_decision", None)

    parameters = _filter_parameters(
        getattr(call_plan, "parameters", None)
        or getattr(match, "parameters", None)
    )
    record = {
        "schema": "sap-nexus.decision-trace.v1",
        "traceId": trace_id or f"dtrace-{uuid.uuid4()}",
        "recordedAt": now(),
        "utteranceHash": hashlib.sha256(utterance.encode("utf-8")).hexdigest(),
        "decision": decision,
        "capabilityId": getattr(call_plan, "capability_id", None)
        or getattr(match, "capability_id", None),
        "parameters": parameters,
        "slotRoles": _slot_roles(outcome),
        "missingParameters": getattr(outcome, "missing_parameters", None)
        or getattr(match, "missing_parameters", None)
        or [],
        "errorType": getattr(outcome, "error_type", None)
        or getattr(match, "error_type", None),
        "turnId": getattr(outcome, "turn_id", None),
        "frameId": getattr(outcome, "frame_id", None),
        "gatewayTraceId": getattr(outcome, "gateway_trace_id", None),
        "model": _model_label(intent_adapter),
        "userCorrection": _user_correction(outcome),
    }
    if record["decision"] is None:
        record["decision"] = None
        record["errorType"] = record["errorType"] or "unclassifiable-outcome"
    return record


def record_turn(
    utterance: str,
    outcome: Any,
    *,
    intent_adapter: Callable[..., Any] | None = None,
) -> None:
    """Best-effort recording; never raises into the caller's flow."""
    path = resolve_trace_path()
    if path is None:
        return
    try:
        record = build_decision_record(
            utterance, outcome, intent_adapter=intent_adapter
        )
        DecisionTraceStore(path).append(record)
    except Exception as exc:  # noqa: BLE001 - tracing must not break the turn
        print(f"decision trace warning: {exc}", file=sys.stderr)
