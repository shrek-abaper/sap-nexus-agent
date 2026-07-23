import json
from datetime import datetime, timedelta, timezone

from sap_nexus_agent.approval import ApprovalRecord, ApprovalState
from sap_nexus_agent.gateway_client import GatewayClient


def test_local_gateway_uses_no_proxy_opener(monkeypatch):
    opened = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"traceId":"gw-local","capabilityId":"MM.Inventory.GetAvailability","success":true,"errorType":"NONE","messages":[]}'

    class FakeOpener:
        def open(self, http_request, timeout):
            opened["url"] = http_request.full_url
            opened["timeout"] = timeout
            return FakeResponse()

    def fake_build_opener(proxy_handler):
        opened["proxy_handler"] = proxy_handler
        return FakeOpener()

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.nioint.com:8080")
    monkeypatch.setattr("sap_nexus_agent.gateway_client.request.build_opener", fake_build_opener)

    result = GatewayClient("http://127.0.0.1:8080").validate("MM.Inventory.GetAvailability", {"material": "M", "plant": "P"})

    assert result.success is True
    assert opened["url"] == "http://127.0.0.1:8080/capabilities/MM.Inventory.GetAvailability/validate"
    assert opened["proxy_handler"].proxies == {}


def test_execute_post_body_includes_parameter_snapshot_hash_when_approval_present(monkeypatch):
    """Task 18 fix: execute POST body must carry parameterSnapshotHash alongside
    approvalId so the Gateway fail-closed ApprovalGuard can verify the parameter
    snapshot version (guard check #3: record.hash.equals(request.hash)).
    Without this field the guard rejects with APPROVAL_VERSION_MISMATCH even when
    the approval was correctly registered.
    """
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'{"traceId":"gw-exec","capabilityId":"MM.PR.CreateDraft",'
                b'"success":true,"errorType":"NONE","returnMessages":[]}'
            )

    class FakeOpener:
        def open(self, http_request, timeout):
            captured["url"] = http_request.full_url
            captured["body"] = json.loads(http_request.data.decode("utf-8"))
            return FakeResponse()

    monkeypatch.setattr(
        "sap_nexus_agent.gateway_client.request.build_opener",
        lambda handler: FakeOpener(),
    )

    GatewayClient("http://127.0.0.1:8080").execute(
        "MM.PR.CreateDraft",
        {"material": "M001"},
        approval_id="appr-001",
        parameter_snapshot_hash="sha256:abc",
    )

    assert captured["url"] == "http://127.0.0.1:8080/capabilities/MM.PR.CreateDraft/execute"
    assert captured["body"]["approvalId"] == "appr-001"
    assert captured["body"]["parameterSnapshotHash"] == "sha256:abc", (
        "execute body must carry parameterSnapshotHash so the Gateway guard can "
        "verify version match (otherwise APPROVAL_VERSION_MISMATCH)"
    )


def test_approve_sends_service_token_only_in_header(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"approvalId":"appr-001"}'

    class FakeOpener:
        def open(self, http_request, timeout):
            captured["url"] = http_request.full_url
            captured["headers"] = dict(http_request.header_items())
            captured["body"] = http_request.data.decode("utf-8")
            return FakeResponse()

    monkeypatch.setenv("SAP_NEXUS_APPROVAL_TOKEN", "approval-service-secret")
    monkeypatch.setattr(
        "sap_nexus_agent.gateway_client.request.build_opener",
        lambda handler: FakeOpener(),
    )
    now = datetime.now(timezone.utc)
    record = ApprovalRecord(
        approval_id="appr-001",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:abc",
        parameters={"material": "M001"},
        approver="user",
        approved_at=now,
        expires_at=now + timedelta(seconds=600),
        status=ApprovalState.approved,
    )

    GatewayClient("http://127.0.0.1:8080").approve("MM.PR.CreateDraft", record)

    assert captured["headers"]["X-sap-nexus-approval-token"] == "approval-service-secret"
    assert "approval-service-secret" not in captured["url"]
    assert "approval-service-secret" not in captured["body"]
