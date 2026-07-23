from __future__ import annotations

from dataclasses import dataclass
import uuid
from typing import Any


@dataclass(frozen=True)
class CallPlan:
    agent_trace_id: str
    capability_id: str
    kind: str
    parameters: dict[str, str]
    validation_policy: str
    created_by: str
    requires_approval: bool

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CallPlan":
        return cls(
            agent_trace_id=str(payload.get("agentTraceId", "")),
            capability_id=str(payload.get("capabilityId", "")),
            kind=str(payload.get("kind", "Function")),
            parameters={
                str(key): str(value)
                for key, value in dict(payload.get("parameters") or {}).items()
            },
            validation_policy=str(payload.get("validationPolicy", "")),
            created_by=str(payload.get("createdBy", "")),
            requires_approval=bool(payload.get("requiresApproval", False)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "agentTraceId": self.agent_trace_id,
            "capabilityId": self.capability_id,
            "kind": self.kind,
            "parameters": dict(self.parameters),
            "validationPolicy": self.validation_policy,
            "createdBy": self.created_by,
            "requiresApproval": self.requires_approval,
        }


def create_call_plan(
    capability_id: str,
    parameters: dict[str, str],
    *,
    kind: str = "Function",
) -> CallPlan:
    normalized_parameters = dict(parameters)
    requires_approval = kind == "Action"
    return CallPlan(
        agent_trace_id=f"agent-{uuid.uuid4()}",
        capability_id=capability_id,
        kind=kind,
        parameters=normalized_parameters,
        validation_policy="validate_before_execute",
        created_by="agent",
        requires_approval=requires_approval,
    )
