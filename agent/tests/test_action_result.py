from __future__ import annotations

from sap_nexus_agent.action_result import ActionResult


def test_from_dict_success():
    payload = {
        "traceId": "trace-001",
        "capabilityId": "MM.PR.CreateDraft",
        "success": True,
        "prNumber": "0010001234",
        "commitStatus": "committed",
        "returnMessages": [],
        "durationMs": 150,
        "errorType": "NONE",
    }
    result = ActionResult.from_dict(payload)
    assert result.success is True
    assert result.pr_number == "0010001234"
    assert result.commit_status == "committed"
    assert result.error_type == "NONE"


def test_from_dict_approval_required():
    payload = {
        "traceId": "trace-002",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "none",
        "returnMessages": [],
        "durationMs": 1,
        "errorType": "APPROVAL_REQUIRED",
    }
    result = ActionResult.from_dict(payload)
    assert result.success is False
    assert result.pr_number == ""
    assert result.commit_status == "none"
    assert result.error_type == "APPROVAL_REQUIRED"


def test_from_dict_sap_business_error_rolled_back():
    payload = {
        "traceId": "trace-003",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "rolled_back",
        "returnMessages": [{"type": "E", "message": "Material not found"}],
        "durationMs": 80,
        "errorType": "SAP_BUSINESS_ERROR",
    }
    result = ActionResult.from_dict(payload)
    assert result.success is False
    assert result.commit_status == "rolled_back"
    assert result.error_type == "SAP_BUSINESS_ERROR"
    assert len(result.return_messages) == 1
