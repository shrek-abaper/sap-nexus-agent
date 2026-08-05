from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ApprovalState(str, Enum):
    pending = "pending"
    approved = "approved"
    executed = "executed"
    rejected = "rejected"


class InvalidApprovalTransition(Exception):
    """Raised when an approval state transition is not permitted."""


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    capability_id: str
    parameter_snapshot_hash: str
    parameters: dict[str, str]
    approver: str
    approved_at: datetime
    expires_at: datetime
    status: ApprovalState
    registry_snapshot_id: str = ""
    capability_version: str = ""
    approval_subject_hash: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalRecord":
        return cls(
            approval_id=str(payload.get("approvalId", "")),
            capability_id=str(payload.get("capabilityId", "")),
            parameter_snapshot_hash=str(payload.get("parameterSnapshotHash", "")),
            parameters={
                str(key): str(value)
                for key, value in dict(payload.get("parameters") or {}).items()
            },
            approver=str(payload.get("approver", "")),
            approved_at=datetime.fromisoformat(str(payload.get("approvedAt", ""))),
            expires_at=datetime.fromisoformat(str(payload.get("expiresAt", ""))),
            status=ApprovalState(str(payload.get("status", ""))),
            registry_snapshot_id=str(payload.get("registrySnapshotId", "")),
            capability_version=str(payload.get("capabilityVersion", "")),
            approval_subject_hash=str(payload.get("approvalSubjectHash", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "approvalId": self.approval_id,
            "capabilityId": self.capability_id,
            "parameterSnapshotHash": self.parameter_snapshot_hash,
            "parameters": dict(self.parameters),
            "approver": self.approver,
            "approvedAt": self.approved_at.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "status": self.status.value,
        }
        if self.registry_snapshot_id:
            payload["registrySnapshotId"] = self.registry_snapshot_id
        if self.capability_version:
            payload["capabilityVersion"] = self.capability_version
        if self.approval_subject_hash:
            payload["approvalSubjectHash"] = self.approval_subject_hash
        return payload


def compute_parameter_hash(parameters: dict[str, str]) -> str:
    canonical = json.dumps(
        parameters,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


_DEFAULT_TTL_SECONDS = 600
_TRACE_FILENAME = "approval.jsonl"


def _resolve_ttl(ttl_seconds: int | None) -> int:
    if ttl_seconds is not None:
        return ttl_seconds
    env_val = os.environ.get("SAP_NEXUS_APPROVAL_TTL_SECONDS")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            return _DEFAULT_TTL_SECONDS
    return _DEFAULT_TTL_SECONDS


def _trace_dir() -> Path:
    return Path(os.environ.get("SAP_NEXUS_TRACE_DIR", "runtime/traces"))


def _append_trace_event(
    record: ApprovalRecord,
    from_state: ApprovalState | None,
    to_state: ApprovalState,
) -> None:
    event = {
        "traceId": str(uuid.uuid4()),
        "approvalId": record.approval_id,
        "capabilityId": record.capability_id,
        "parameterSnapshotHash": record.parameter_snapshot_hash,
        "parametersSummary": {
            "keys": sorted(record.parameters.keys()),
            "count": len(record.parameters),
        },
        "approver": record.approver,
        "fromState": from_state.value if from_state is not None else None,
        "toState": to_state.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    trace_dir = _trace_dir()
    trace_dir.mkdir(parents=True, exist_ok=True)
    with (trace_dir / _TRACE_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def create_approval_record(
    capability_id: str,
    parameters: dict[str, str],
    approver: str,
    ttl_seconds: int | None = None,
    registry_snapshot_id: str = "",
    capability_version: str = "",
    approval_subject_hash: str = "",
) -> ApprovalRecord:
    now = datetime.now(timezone.utc)
    record = ApprovalRecord(
        approval_id=f"appr-{uuid.uuid4()}",
        capability_id=capability_id,
        parameter_snapshot_hash=compute_parameter_hash(parameters),
        parameters=dict(parameters),
        approver=approver,
        approved_at=now,
        expires_at=now + timedelta(seconds=_resolve_ttl(ttl_seconds)),
        status=ApprovalState.pending,
        registry_snapshot_id=registry_snapshot_id,
        capability_version=capability_version,
        approval_subject_hash=approval_subject_hash,
    )
    _append_trace_event(record, None, ApprovalState.pending)
    return record


def _transition(
    record: ApprovalRecord,
    target: ApprovalState,
    allowed_from: tuple[ApprovalState, ...],
) -> ApprovalRecord:
    if record.status not in allowed_from:
        raise InvalidApprovalTransition(
            f"Cannot transition {record.status.value} -> {target.value}; "
            f"allowed from: {[s.value for s in allowed_from]}"
        )
    from_state = record.status
    updates: dict[str, Any] = {"status": target}
    if target is ApprovalState.approved:
        updates["approved_at"] = datetime.now(timezone.utc)
    new_record = dataclasses.replace(record, **updates)
    _append_trace_event(new_record, from_state, target)
    return new_record


def approve(record: ApprovalRecord) -> ApprovalRecord:
    return _transition(record, ApprovalState.approved, (ApprovalState.pending,))


def mark_executed(record: ApprovalRecord) -> ApprovalRecord:
    return _transition(record, ApprovalState.executed, (ApprovalState.approved,))


def reject(record: ApprovalRecord) -> ApprovalRecord:
    return _transition(
        record,
        ApprovalState.rejected,
        (ApprovalState.pending, ApprovalState.approved),
    )


def is_expired(record: ApprovalRecord, now: datetime) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now > record.expires_at
