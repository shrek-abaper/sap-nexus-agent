from __future__ import annotations

import json
import os
from typing import Protocol
from urllib import parse
from urllib import error, request

from sap_nexus_agent.approval import ApprovalRecord
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult


class GatewayClientProtocol(Protocol):
    def validate(self, capability_id: str, parameters: dict[str, str]) -> ValidationResult:
        ...

    def approve(self, capability_id: str, approval_record: ApprovalRecord) -> str:
        ...

    def execute(
        self,
        capability_id: str,
        parameters: dict[str, str],
        approval_id: str | None = None,
        parameter_snapshot_hash: str | None = None,
    ) -> ExecutionResult:
        ...


class GatewayClient:
    def __init__(self, base_url: str = "http://localhost:8080", timeout_seconds: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._opener = _build_opener(self.base_url)

    def validate(self, capability_id: str, parameters: dict[str, str]) -> ValidationResult:
        payload = self._post(f"/capabilities/{capability_id}/validate", parameters)
        return ValidationResult.from_dict(payload)

    def approve(self, capability_id: str, approval_record: ApprovalRecord) -> str:
        """Register an approved ApprovalRecord with the Gateway so the fail-closed
        ApprovalGuard at the execute entry can find it (Task 18 registration channel).
        Returns the approvalId echoed by the Gateway, or an empty string on failure.
        """
        body = json.dumps(approval_record.to_dict()).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        approval_token = os.environ.get("SAP_NEXUS_APPROVAL_TOKEN", "")
        if approval_token:
            headers["X-SAP-Nexus-Approval-Token"] = approval_token
        http_request = request.Request(
            f"{self.base_url}/capabilities/{capability_id}/approve",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with self._opener.open(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return str(payload.get("approvalId", ""))
        except error.HTTPError as exc:
            return str(json.loads(exc.read().decode("utf-8")).get("approvalId", ""))

    def execute(
        self,
        capability_id: str,
        parameters: dict[str, str],
        approval_id: str | None = None,
        parameter_snapshot_hash: str | None = None,
    ) -> ExecutionResult:
        payload = self._post(
            f"/capabilities/{capability_id}/execute",
            parameters,
            approval_id,
            parameter_snapshot_hash,
        )
        return ExecutionResult.from_dict(payload)

    def _post(
        self,
        path: str,
        parameters: dict[str, str],
        approval_id: str | None = None,
        parameter_snapshot_hash: str | None = None,
    ) -> dict[str, object]:
        body_dict: dict[str, object] = {"parameters": dict(parameters)}
        if approval_id is not None:
            body_dict["approvalId"] = approval_id
        if parameter_snapshot_hash is not None:
            body_dict["parameterSnapshotHash"] = parameter_snapshot_hash
        body = json.dumps(body_dict).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(http_request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return json.loads(exc.read().decode("utf-8"))


def _build_opener(base_url: str):
    host = parse.urlsplit(base_url).hostname
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return request.build_opener(request.ProxyHandler({}))
    return request.build_opener()
