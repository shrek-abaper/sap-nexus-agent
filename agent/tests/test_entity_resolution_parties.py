"""Phase C tests: Customer/Supplier reuse of the same resolution mechanism.

The same EntityResolutionService + ENTITY_CHOICE protocol resolves all three
object types from ontology declarations — no per-object state machines. The
slot NAME mapping is declarative: Customer binds to `customer` (FI.AR) or
`customerNumber` (SD.SO), Supplier binds to `vendor` (MM.PO/FI.AP).
"""

from __future__ import annotations

import pytest

from sap_nexus_agent.conversation_context import ConversationContext
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.governed_context import PLACEHOLDER_PRINCIPAL
from sap_nexus_agent.orchestrator import run_query
from sap_nexus_agent.read_context import ConversationReadState

AR = "FI.AR.GetOpenItems"
SO = "SD.SalesOrder.GetList"
AP = "FI.AP.GetOpenItems"

MD_BY_CAPABILITY = {
    "MD.Customer.Search": "sapnexus:Customer",
    "MD.Supplier.Search": "sapnexus:Supplier",
}


def _party_candidates(object_type: str, rows: list[dict]) -> list[dict]:
    return [
        {
            "sourceSystem": "S4H",
            "client": "100",
            "objectType": object_type,
            "canonicalCode": row["code"],
            "displayName": row["name"],
            "distinguishing": {"city": row["city"], "country": "CN"},
            "matchKind": row.get("match", "substring"),
            "status": "active",
            "orgScopes": [{"field": "companyCode", "value": "1000"}],
        }
        for row in rows
    ]


CUSTOMERS = [
    {"code": "C10001", "name": "华远机械（苏州）有限公司", "city": "苏州"},
    {"code": "C10002", "name": "华远机械（天津）有限公司", "city": "天津"},
]
SUPPLIERS = [
    {"code": "V10001", "name": "宏达精密五金（东莞）有限公司", "city": "东莞", "match": "approved-alias"},
    {"code": "V10002", "name": "宏达塑胶（苏州）有限公司", "city": "苏州", "match": "approved-alias"},
]


class FakeGateway:
    def __init__(self):
        self.execute_calls: list[tuple[str, dict]] = []
        self.validate_calls: list[tuple[str, dict]] = []

    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, parameters))
        return ValidationResult(
            trace_id="gw-validate", capability_id=capability_id,
            success=True, error_type="NONE", messages=[],
        )

    def execute(self, capability_id, parameters, approval_id=None):
        self.execute_calls.append((capability_id, dict(parameters)))
        object_type = MD_BY_CAPABILITY.get(capability_id)
        if object_type is not None:
            pool = CUSTOMERS if object_type == "sapnexus:Customer" else SUPPLIERS
            query = str(parameters.get("query") or "")
            entity_key = str(parameters.get("entityKey") or "")
            rows = pool
            if entity_key:
                rows = [r for r in rows if r["code"].upper() == entity_key.upper()]
            elif query:
                rows = [
                    r for r in rows
                    if query in r["name"] or query in r["city"]
                    or (object_type == "sapnexus:Supplier" and query == "宏达")
                ]
            return ExecutionResult(
                trace_id="gw-md", capability_id=capability_id,
                success=True, executor={"type": "PG_MASTERDATA_READ", "rfcName": None},
                return_messages=[],
                data={
                    "candidates": _party_candidates(object_type, rows),
                    "objectType": object_type,
                    "snapshotId": "snap-parties-1",
                    "resultCompleteness": "complete-result-set",
                    "sourceExtractedAt": "2026-10-01T00:00:00Z",
                },
                duration_ms=5, error_type="NONE",
            )
        if capability_id in (AR, SO, AP):
            return ExecutionResult(
                trace_id="gw-biz", capability_id=capability_id,
                success=True,
                executor={"type": "JCO_RFC", "rfcName": "BAPI_X"},
                return_messages=[], data={"rows": []},
                duration_ms=10, error_type="NONE",
            )
        raise AssertionError(f"unexpected gateway execute: {capability_id}")


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "on")


@pytest.fixture()
def gateway():
    return FakeGateway()


def _turn(text, gateway, context=None):
    if context is None:
        context = ConversationContext(
            None, None, read_state=ConversationReadState(None, None, 0),
        )
    return run_query(text, gateway, context=context, principal=PLACEHOLDER_PRINCIPAL)


def _biz_calls(gateway, capability_id):
    return [params for cap, params in gateway.execute_calls if cap == capability_id]


def test_customer_binds_to_ar_customer_slot(gateway):
    first = _turn("华远机械在公司代码 1000 的未清应收", gateway)
    assert first.entity_choice is not None
    assert first.entity_choice["targetSlot"] == "customer"
    assert [c["canonicalCode"] for c in first.entity_choice["candidates"]] == ["C10001", "C10002"]
    assert _biz_calls(gateway, AR) == []

    second = _turn("第一个", gateway, context=first.updated_context)
    calls = _biz_calls(gateway, AR)
    # case 24/25: same mechanism; the AR slot is named `customer`
    assert len(calls) == 1 and calls[0]["customer"] == "C10001"


def test_customer_number_binding_is_declared_but_optional_slots_do_not_trigger(gateway):
    """Case 25 boundary (v1): the Customer -> customerNumber mapping is
    declared and cross-validated (test_entity_resolution_rules), but v1 only
    triggers resolution for REQUIRED slots. Optional filter slots (SD.SO)
    keep legacy behavior; triggering them needs an intent signal and is a
    documented gap."""
    from sap_nexus_agent.entity_resolution import load_resolution_rules, validate_rules

    rules = load_resolution_rules()
    assert validate_rules(rules) == ()
    customer = next(r for r in rules if r.object_type_id == "sapnexus:Customer")
    bindings = {(b.capability_id, b.input_name) for b in customer.parameter_bindings}
    assert ("SD.SalesOrder.GetList", "customerNumber") in bindings

    outcome = _turn("华远机械的销售订单", gateway)
    assert outcome.entity_choice is None  # optional slot: no resolution in v1


def test_supplier_alias_binds_to_ap_vendor_slot(gateway):
    first = _turn("宏达在公司代码 1000 的应付未清项", gateway)
    assert first.entity_choice is not None
    assert first.entity_choice["targetSlot"] == "vendor"
    assert [c["canonicalCode"] for c in first.entity_choice["candidates"]] == ["V10001", "V10002"]

    second = _turn("苏州的那家", gateway, context=first.updated_context)
    calls = _biz_calls(gateway, AP)
    assert len(calls) == 1 and calls[0]["vendor"] == "V10002"


def test_object_types_do_not_cross_bind(gateway):
    # case 5/23: a Supplier resolution never fills a Customer slot
    first = _turn("宏达在公司代码 1000 的应付未清项", gateway)
    assert first.entity_choice["objectType"] == "sapnexus:Supplier"
    second = _turn("第一个", gateway, context=first.updated_context)
    calls = _biz_calls(gateway, AP)
    assert calls and "vendor" in calls[0] and "customer" not in calls[0]
