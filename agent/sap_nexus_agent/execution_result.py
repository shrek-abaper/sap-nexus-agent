from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    trace_id: str
    capability_id: str
    success: bool
    error_type: str
    messages: list[str]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ValidationResult":
        return cls(
            trace_id=str(payload.get("traceId", "")),
            capability_id=str(payload.get("capabilityId", "")),
            success=bool(payload.get("success", False)),
            error_type=str(payload.get("errorType", "UNKNOWN")),
            messages=[str(message) for message in payload.get("messages", [])],
        )


@dataclass(frozen=True)
class ExecutionResult:
    trace_id: str
    capability_id: str
    success: bool
    executor: dict[str, Any]
    return_messages: list[dict[str, Any]]
    data: dict[str, Any]
    duration_ms: int
    error_type: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutionResult":
        data = dict(payload.get("data") or {})
        # Absorb write-path top-level fields into data for unified access.
        # The Gateway WRITE response returns prNumber/commitStatus at the top
        # level (ActionResult shape); read paths keep using nested data.
        if "prNumber" in payload:
            data["prNumber"] = payload["prNumber"]
        if "commitStatus" in payload:
            data["commitStatus"] = payload["commitStatus"]
        return cls(
            trace_id=str(payload.get("traceId", "")),
            capability_id=str(payload.get("capabilityId", "")),
            success=bool(payload.get("success", False)),
            executor=dict(payload.get("executor") or {}),
            return_messages=[dict(message) for message in payload.get("returnMessages", [])],
            data=data,
            duration_ms=int(payload.get("durationMs", 0)),
            error_type=str(payload.get("errorType", "UNKNOWN")),
        )
