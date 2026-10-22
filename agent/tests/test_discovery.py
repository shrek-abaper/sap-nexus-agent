"""Tests for sap_nexus_agent.discovery (master-data directory + capability catalog)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sap_nexus_agent.discovery import list_capabilities, list_master_data


class FakeGateway:
    def __init__(self, execution=None, error: Exception | None = None):
        self.execution = execution
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def execute(self, capability_id, parameters):
        self.calls.append((capability_id, dict(parameters)))
        if self.error is not None:
            raise self.error
        return self.execution


def _execution(data, *, success=True, error_type="NONE"):
    return SimpleNamespace(success=success, error_type=error_type, data=data)


CANDIDATE_PAYLOAD = {
    "candidates": [
        {
            "canonicalCode": "DEMOA1",
            "displayName": "蓝色耐高温密封圈 Ø20",
            "matchKind": "browse",
            "status": "active",
            "distinguishing": {"materialGroup": "SEAL", "sizeDimension": "20mm"},
            "orgScopes": [{"field": "plant", "value": "1000"}],
        },
        {
            "canonicalCode": "DEMOA2",
            "displayName": "蓝色耐高温密封圈 Ø25",
            "matchKind": "browse",
            "status": "active",
            "distinguishing": {},
            "orgScopes": [],
        },
    ],
    "snapshotId": "snap1",
    "resultCompleteness": "complete-result-set",
    "sourceExtractedAt": "2026-10-01",
}


def test_browse_without_query_sends_no_query_parameter():
    gateway = FakeGateway(_execution(CANDIDATE_PAYLOAD))

    result = list_master_data(object_type="sapnexus:Material", gateway=gateway)

    assert result["status"] == "complete"
    capability_id, parameters = gateway.calls[0]
    assert capability_id == "MD.Material.Search"
    assert "query" not in parameters
    assert result["capabilityId"] == "MD.Material.Search"
    assert result["snapshotId"] == "snap1"
    assert result["resultCompleteness"] == "complete-result-set"
    assert [c["canonicalCode"] for c in result["candidates"]] == ["DEMOA1", "DEMOA2"]
    first = result["candidates"][0]
    assert first["displayName"] == "蓝色耐高温密封圈 Ø20"
    assert first["distinguishing"] == {"materialGroup": "SEAL", "sizeDimension": "20mm"}
    assert first["orgScopes"] == [{"field": "plant", "value": "1000"}]


def test_query_and_org_filter_map_to_declared_fields():
    gateway = FakeGateway(_execution(CANDIDATE_PAYLOAD))

    list_master_data(
        object_type="sapnexus:Material",
        gateway=gateway,
        query=" 密封圈 ",
        org_filter="1000",
        limit=10,
    )

    _, parameters = gateway.calls[0]
    assert parameters == {"query": "密封圈", "plant": "1000", "limit": "10"}


def test_org_filter_uses_each_object_types_declared_field():
    gateway = FakeGateway(_execution(CANDIDATE_PAYLOAD))

    list_master_data(object_type="sapnexus:Customer", gateway=gateway, org_filter="1000")

    capability_id, parameters = gateway.calls[0]
    assert capability_id == "MD.Customer.Search"
    assert parameters == {"companyCode": "1000"}


def test_unknown_object_type_is_invalid_and_never_calls_gateway():
    gateway = FakeGateway(_execution(CANDIDATE_PAYLOAD))

    result = list_master_data(object_type="sapnexus:CostCenter", gateway=gateway)

    assert result["status"] == "invalid"
    assert "sapnexus:Material" in result["message"]
    assert gateway.calls == []


def test_permission_error_maps_to_permission_denied():
    gateway = FakeGateway(_execution({}, success=False, error_type="MASTERDATA_PERMISSION_DENIED"))

    result = list_master_data(object_type="sapnexus:Material", gateway=gateway)

    assert result["status"] == "permission-denied"
    assert result["candidates"] == []


def test_failure_and_exception_map_to_unavailable():
    failing = FakeGateway(_execution({}, success=False, error_type="MASTERDATA_UNAVAILABLE"))
    raising = FakeGateway(error=ConnectionError("refused"))

    assert list_master_data(object_type="sapnexus:Material", gateway=failing)["status"] == "unavailable"
    assert list_master_data(object_type="sapnexus:Material", gateway=raising)["status"] == "unavailable"


def test_list_capabilities_projects_registry_snapshot():
    result = list_capabilities()

    assert result["status"] == "complete"
    assert result["snapshotId"]
    by_id = {entry["capabilityId"]: entry for entry in result["capabilities"]}
    assert "MD.Material.Search" in by_id
    search = by_id["MD.Material.Search"]
    assert search["domain"] == "MD"
    assert search["sideEffect"] == "none"
    assert search["requiresApproval"] is False
    assert search["description"]
    write = by_id["MM.PR.CreateDraft"]
    assert write["sideEffect"] == "sap_write"
    assert write["requiresApproval"] is True
    assert "material" in write["requiredInputs"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
