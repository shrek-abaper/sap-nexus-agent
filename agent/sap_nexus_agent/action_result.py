from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionResult:
    trace_id: str
    capability_id: str
    success: bool
    pr_number: str
    commit_status: str
    return_messages: list[dict[str, Any]]
    duration_ms: int
    error_type: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionResult":
        return cls(
            trace_id=str(payload.get("traceId", "")),
            capability_id=str(payload.get("capabilityId", "")),
            success=bool(payload.get("success", False)),
            pr_number=str(payload.get("prNumber", "")),
            commit_status=str(payload.get("commitStatus", "none")),
            return_messages=[dict(message) for message in payload.get("returnMessages", [])],
            duration_ms=int(payload.get("durationMs", 0)),
            error_type=str(payload.get("errorType", "UNKNOWN")),
        )
