from pathlib import Path

from sap_nexus_agent.eval import FakeGatewayClient, run_eval_file

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_inventory_eval_file_passes():
    summary = run_eval_file(REPO_ROOT / "evals" / "inventory_availability_cases.yaml")

    assert summary.total >= 6
    assert summary.failed == 0
    assert summary.passed == summary.total


def test_eval_harness_seed_cases_pass_contract():
    summary = run_eval_file(REPO_ROOT / "evals" / "eval_harness_seed_cases.json")

    assert summary.total >= 13
    assert summary.failed == 0
    assert summary.passed == summary.total


def test_pr_create_eval_file_passes():
    summary = run_eval_file(REPO_ROOT / "evals" / "pr_create_cases.json")

    assert summary.total == 9
    assert summary.failed == 0
    assert summary.passed == summary.total


def test_po_seed_cases_route_via_run_query():
    """PO seed cases (bc_mm_purchaseorder_*) route through run_query and pass."""
    import json

    payload = json.loads((REPO_ROOT / "evals" / "eval_harness_seed_cases.json").read_text("utf-8"))
    po_case_ids = [c["caseId"] for c in payload["cases"] if c["caseId"].startswith("bc_mm_purchaseorder_")]
    assert len(po_case_ids) >= 7

    summary = run_eval_file(REPO_ROOT / "evals" / "eval_harness_seed_cases.json")
    assert summary.failed == 0
    assert summary.passed == summary.total


def _inventory_case() -> dict:
    return {
        "caseId": "fake-gateway-signature-probe",
        "utterance": "查物料 DEMOA1 在工厂 1000 的可用库存",
        "expectedCapabilityId": "MM.Inventory.GetAvailability",
    }


def test_fake_gateway_execute_accepts_approval_id_keyword():
    """FakeGatewayClient.execute must accept approval_id kw (matches GatewayClientProtocol)."""
    fake = FakeGatewayClient(_inventory_case())
    result = fake.execute(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA1", "plant": "1000"},
        approval_id="ap-write-001",
    )
    assert result.success is True
    # approval_id recorded for write-path tracing parity with real gateway
    assert fake.execute_calls[-1][0] == "MM.Inventory.GetAvailability"


def test_fake_gateway_execute_accepts_approval_id_positional():
    """FakeGatewayClient.execute must accept approval_id as 3rd positional arg."""
    fake = FakeGatewayClient(_inventory_case())
    result = fake.execute(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA1", "plant": "1000"},
        "ap-write-002",
    )
    assert result.success is True


def test_fake_gateway_execute_backward_compatible_without_approval_id():
    """Read path: calling execute without approval_id still works (default None)."""
    fake = FakeGatewayClient(_inventory_case())
    result = fake.execute(
        "MM.Inventory.GetAvailability",
        {"material": "DEMOA1", "plant": "1000"},
    )
    assert result.success is True
    assert len(fake.execute_calls) == 1


def test_fake_gateway_execute_signature_matches_gateway_client_protocol():
    """FakeGatewayClient.execute signature must match GatewayClientProtocol.execute."""
    import inspect

    from sap_nexus_agent.gateway_client import GatewayClientProtocol

    proto_params = list(inspect.signature(GatewayClientProtocol.execute).parameters.items())
    fake_params = list(inspect.signature(FakeGatewayClient.execute).parameters.items())

    assert [name for name, _ in proto_params] == [name for name, _ in fake_params]
    # approval_id must default to None for read-path backward compatibility
    fake_approval = fake_params[-1][1]
    assert fake_approval.default is None
