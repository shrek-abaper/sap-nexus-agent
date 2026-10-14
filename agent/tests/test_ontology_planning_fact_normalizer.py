"""TypedFactNormalizer tests (allowlist-driven, identity-preserving)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sap_nexus_agent.ontology_planning.contracts import NodeResult
from sap_nexus_agent.ontology_planning.fact_normalizer import normalize
from sap_nexus_agent.ontology_planning.release import pin_release

REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTED = "2026-10-14T00:00:00Z"


@pytest.fixture(scope="module")
def pinned():
    return pin_release(REPO_ROOT)


FACT_TYPES = {
    "MM.PurchaseOrder.GetList": "sapnexus:PurchaseOrderSupplyFact",
    "MM.Inventory.GetAvailability": "sapnexus:InventoryAvailabilityFact",
    "MM.Material.GetInfo": "sapnexus:MaterialInfoFact",
}


def _node(node_id, capability_id, data, parameters=None):
    return NodeResult(
        node_id=node_id,
        capability_id=capability_id,
        parameters=dict(parameters or {"material": "DEMOA2", "plant": "1000"}),
        gateway_trace_id=f"fake-{node_id}",
        executed_at=COLLECTED,
        data=data,
    )


def test_po_header_items_expand_once_with_fallback(pinned):
    node = _node("read-1", "MM.PurchaseOrder.GetList", {
        "purchaseOrders": [
            {
                "purchaseOrder": "4500000001",
                "supplier": "V72719",
                "purchaseOrderUnit": "EA",
                "orderQuantity": "999",
                "items": [
                    {"purchaseOrderItem": "00010", "orderQuantity": "100"},
                    {"purchaseOrderItem": "00020", "orderQuantity": "150",
                     "purchaseOrderUnit": "KG"},
                ],
            }
        ]
    })
    result = normalize((node,), pinned, run_id="run-1", fact_types=FACT_TYPES)
    facts = result.facts
    assert len(facts) == 2
    rows = {f.object_key["purchaseOrderItem"]: f for f in facts}
    assert rows["00010"].fields["orderQuantity"].value == "100"
    assert rows["00010"].fields["purchaseOrderUnit"].value == "EA"
    assert rows["00020"].fields["orderQuantity"].value == "150"
    assert rows["00020"].fields["purchaseOrderUnit"].value == "KG"
    assert rows["00010"].fields["supplier"].value == "V72719"
    assert len(rows["00010"].evidence.raw_fields) >= 4
    assert all(f.evidence.completeness == "complete" for f in facts)


def test_non_finite_quantity_excluded(pinned):
    node = _node("read-1", "MM.PurchaseOrder.GetList", {
        "purchaseOrders": [
            {"purchaseOrder": "4500000001", "purchaseOrderItem": "00010",
             "supplier": "V72719", "orderQuantity": "abc",
             "purchaseOrderUnit": "EA"}
        ]
    })
    result = normalize((node,), pinned, run_id="run-1", fact_types=FACT_TYPES)
    assert result.facts == ()
    assert any(e.reason == "NON_FINITE_MEASURE" for e in result.exclusions)


def test_inventory_scalar_without_mrp_fields(pinned):
    node = _node("read-0", "MM.Inventory.GetAvailability", {
        "availableQuantity": "12.000",
        "mrpElementLines": [{"indicator": "WB", "quantity": "12.000"}],
        "returnMessages": [],
    })
    result = normalize((node,), pinned, run_id="run-1", fact_types=FACT_TYPES)
    assert len(result.facts) == 1
    fact = result.facts[0]
    assert set(fact.fields) == {"availableQuantity"}
    assert fact.fields["availableQuantity"].value == "12.000"
    assert fact.definition_ref is None


def test_material_scalar_fact(pinned):
    node = _node("read-0", "MM.Material.GetInfo", {
        "material": "DEMOA2",
        "plant": "1000",
        "baseUnitOfMeasure": "EA",
        "purchasingGroup": "001",
    })
    result = normalize((node,), pinned, run_id="run-1", fact_types=FACT_TYPES)
    assert len(result.facts) == 1
    assert result.facts[0].fields["baseUnitOfMeasure"].value == "EA"


def test_duplicate_row_identity_conflict(pinned):
    node = _node("read-1", "MM.PurchaseOrder.GetList", {
        "purchaseOrders": [
            {"purchaseOrder": "4500000001", "purchaseOrderItem": "00010",
             "supplier": "V72719", "orderQuantity": "100",
             "purchaseOrderUnit": "EA"},
            {"purchaseOrder": "4500000001", "purchaseOrderItem": "00010",
             "supplier": "V72719", "orderQuantity": "100",
             "purchaseOrderUnit": "EA"},
        ]
    })
    result = normalize((node,), pinned, run_id="run-1", fact_types=FACT_TYPES)
    assert result.conflicts
    assert all("4500000001" in c for c in result.conflicts)


def test_non_allowlisted_payload_field_dropped(pinned):
    node = _node("read-0", "MM.Inventory.GetAvailability", {
        "availableQuantity": "12.000",
        "deliveryDate": "2026-10-21",
    })
    result = normalize((node,), pinned, run_id="run-1", fact_types=FACT_TYPES)
    assert set(result.facts[0].fields) == {"availableQuantity"}
