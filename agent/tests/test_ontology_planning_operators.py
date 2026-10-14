"""Tests for the four deterministic analysis operators."""

from __future__ import annotations

from decimal import Decimal

from sap_nexus_agent.ontology_planning.contracts import (
    FactEvidence,
    TypedFact,
    TypedFieldValue,
)
from sap_nexus_agent.ontology_planning.operators import (
    compare,
    filter_eq,
    group_sum,
    select_fields,
)

V = "0.1.0"


def _po_fact(fact_id, po, item, supplier, quantity, unit, material="DEMOA2"):
    return TypedFact(
        fact_id=fact_id,
        fact_type_ref="sapnexus:PurchaseOrderSupplyFact",
        object_type="PurchaseOrderItem",
        object_key={"purchaseOrder": po, "purchaseOrderItem": item},
        scope={"plant": "1000"},
        row_identity={"purchaseOrder": po, "purchaseOrderItem": item},
        fields={
            "purchaseOrder": TypedFieldValue(po, "sapnexus:PurchaseOrderNumber"),
            "purchaseOrderItem": TypedFieldValue(item, "sapnexus:PurchaseOrderItemNumber"),
            "supplier": TypedFieldValue(supplier, "sapnexus:Supplier"),
            "material": TypedFieldValue(material, "sapnexus:MaterialNumber"),
            "orderQuantity": TypedFieldValue(quantity, "sapnexus:Quantity"),
            "purchaseOrderUnit": TypedFieldValue(unit, "sapnexus:UnitOfMeasure"),
        },
        unit={"field": "purchaseOrderUnit", "value": unit},
        business_time=None,
        collected_at="2026-10-14T00:00:00Z",
        definition_ref=None,
        evidence=FactEvidence("run-1", "read-1", "fake-1",
                              ("orderQuantity",), "complete"),
    )


def _facts():
    return (
        _po_fact("read-1:row:0", "4500000001", "00010", "V72719", "100", "EA"),
        _po_fact("read-1:row:1", "4500000001", "00020", "V72719", "150", "EA"),
        _po_fact("read-1:row:2", "4500000002", "00010", "V88888", "40", "KG"),
        _po_fact("read-1:row:3", "4500000003", "00010", "V88888", "5", "KG"),
    )


def test_select_fields_keeps_lineage_and_subset():
    result = select_fields("a1", _facts(), {"fields": ["supplier", "orderQuantity"]}, V)
    assert result.status == "complete"
    assert all(set(row["fields"]) == {"supplier", "orderQuantity"} for row in result.rows)
    assert {row["factId"] for row in result.rows} == {f"read-1:row:{i}" for i in range(4)}


def test_filter_eq_typed_literal():
    result = filter_eq("a1", _facts(), {"field": "supplier", "value": "V72719"}, V)
    assert len(result.rows) == 2
    assert all(row["fields"]["supplier"]["value"] == "V72719" for row in result.rows)


def test_group_sum_by_supplier_and_unit_reconciles_lineage():
    result = group_sum(
        "a1", _facts(),
        {"dimensions": ["supplier"], "measure": "orderQuantity",
         "unitField": "purchaseOrderUnit"},
        V,
    )
    assert result.status == "complete"
    totals = {
        tuple(row["groupKey"].values()): (row["measures"]["orderQuantity"]["decimal"],
                                          row["measures"]["orderQuantity"]["unit"],
                                          len(row["lineage"]))
        for row in result.rows
    }
    assert totals[("V72719",)] == ("250", "EA", 2)
    assert totals[("V88888",)] == ("45", "KG", 2)
    # Decimal exactness
    direct = Decimal("100") + Decimal("150")
    assert Decimal(totals[("V72719",)][0]) == direct


def test_group_sum_missing_unit_excludes_and_marks_partial():
    facts = list(_facts())
    row = facts[3]
    fields = dict(row.fields)
    fields["purchaseOrderUnit"] = TypedFieldValue("", "sapnexus:UnitOfMeasure")
    facts[3] = TypedFact(
        fact_id=row.fact_id, fact_type_ref=row.fact_type_ref,
        object_type=row.object_type, object_key=row.object_key,
        scope=row.scope, row_identity=row.row_identity, fields=fields,
        unit=None, business_time=None, collected_at=row.collected_at,
        definition_ref=None, evidence=row.evidence,
    )
    result = group_sum(
        "a1", tuple(facts),
        {"dimensions": ["supplier"], "measure": "orderQuantity",
         "unitField": "purchaseOrderUnit"},
        V,
    )
    assert result.partial is True
    assert any(e.reason == "MISSING_UNIT" for e in result.excluded_rows)
    assert any(r["groupKey"]["supplier"] == "V72719" for r in result.rows)


def test_compare_different_units_gaps():
    facts = (
        _po_fact("r0", "1", "10", "V72719", "100", "EA"),
        _po_fact("r1", "2", "10", "V88888", "100", "KG"),
    )
    result = compare(
        "a1", facts,
        {"left": {"factId": "r0", "field": "orderQuantity"},
         "right": {"factId": "r1", "field": "orderQuantity"}},
        V,
    )
    assert result.status == "semantic_gap"
    assert any("INCOMPATIBLE_COMPARISON" in r for r in result.reasons)
    assert result.rows == ()


def test_compare_same_unit_succeeds():
    facts = (
        _po_fact("r0", "1", "10", "V72719", "100", "EA"),
        _po_fact("r1", "2", "10", "V88888", "120", "EA"),
    )
    result = compare(
        "a1", facts,
        {"left": {"factId": "r0", "field": "orderQuantity"},
         "right": {"factId": "r1", "field": "orderQuantity"}},
        V,
    )
    assert result.status == "complete"
    assert result.rows[0]["left"]["decimal"] == "100"
    assert result.rows[0]["right"]["decimal"] == "120"


def test_conflict_blocks_group_sum():
    result = group_sum(
        "a1", _facts(),
        {"dimensions": ["supplier"], "measure": "orderQuantity",
         "unitField": "purchaseOrderUnit"},
        V,
        conflicts=("ROW_IDENTITY_CONFLICT:x",),
    )
    assert result.status == "failed"
    assert result.rows == ()
