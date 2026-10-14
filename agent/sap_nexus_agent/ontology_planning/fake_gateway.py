"""Offline gateway over checked-in fixture envelopes.

Implements the same validate/execute surface used by read execution. Only
the three registered READ capabilities are callable; any WRITE/Action id
raises WriteRejected before any call is recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult

READ_CAPABILITY_IDS = frozenset({
    "MM.Inventory.GetAvailability",
    "MM.PurchaseOrder.GetList",
    "MM.Material.GetInfo",
})


class WriteRejected(RuntimeError):
    """A non-READ capability reached the offline gateway boundary."""


class FixtureNotFound(RuntimeError):
    """The case has no checked-in response fixture for the capability."""


class FakeGatewayClient:
    def __init__(self, fixtures_root: Path, case_id: str):
        self._root = Path(fixtures_root)
        self._case_id = case_id
        self.calls: list[str] = []

    def validate(self, capability_id: str, parameters: dict[str, str]) -> ValidationResult:
        if capability_id not in READ_CAPABILITY_IDS:
            raise WriteRejected(capability_id)
        return ValidationResult(
            trace_id=f"fake-validate-{len(self.calls)}",
            capability_id=capability_id,
            success=True,
            error_type="",
            messages=[],
        )

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
        if capability_id not in READ_CAPABILITY_IDS:
            raise WriteRejected(capability_id)
        path = self._root / "gateway" / self._case_id / f"{capability_id}.json"
        if not path.exists():
            raise FixtureNotFound(str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.calls.append(capability_id)
        payload.setdefault("capabilityId", capability_id)
        payload.setdefault("success", True)
        return ExecutionResult.from_dict(payload)
