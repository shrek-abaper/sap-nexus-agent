"""Contract tests for ontology/entity-resolution.yaml cross-validation."""

from __future__ import annotations

import pytest

from sap_nexus_agent.entity_resolution import (
    load_resolution_rules,
    validate_rules,
)


@pytest.fixture(scope="module")
def rules():
    return load_resolution_rules()


def test_three_object_types_load(rules):
    assert {rule.object_type_id for rule in rules} == {
        "sapnexus:Material",
        "sapnexus:Customer",
        "sapnexus:Supplier",
    }


def test_shipped_rules_pass_cross_validation(rules):
    assert validate_rules(rules) == ()


def test_conservative_confirmation_policy(rules):
    # brief D4: only exact-code may bind without asking, and only with evidence.
    for rule in rules:
        assert rule.confirm_exact_code is False
        assert rule.confirm_exact_label_unique is True


def test_customer_binds_to_both_slot_names(rules):
    customer = next(rule for rule in rules if rule.object_type_id == "sapnexus:Customer")
    bindings = {(b.capability_id, b.input_name) for b in customer.parameter_bindings}
    assert ("FI.AR.GetOpenItems", "customer") in bindings
    assert ("SD.SalesOrder.GetList", "customerNumber") in bindings


def test_supplier_binds_to_vendor_slots(rules):
    supplier = next(rule for rule in rules if rule.object_type_id == "sapnexus:Supplier")
    bindings = {(b.capability_id, b.input_name) for b in supplier.parameter_bindings}
    assert ("MM.PurchaseOrder.GetList", "vendor") in bindings
    assert ("FI.AP.GetOpenItems", "vendor") in bindings


def test_material_binds_to_material_slots(rules):
    material = next(rule for rule in rules if rule.object_type_id == "sapnexus:Material")
    bindings = {(b.capability_id, b.input_name) for b in material.parameter_bindings}
    assert ("MM.Inventory.GetAvailability", "material") in bindings
    assert ("MM.Material.GetInfo", "material") in bindings
    assert ("SD.SalesOrder.GetList", "material") in bindings


def test_unknown_object_type_flagged(rules):
    broken = tuple(
        rule if rule.object_type_id != "sapnexus:Material" else
        type(rule)(**{**rule.__dict__, "object_type_id": "sapnexus:Ghost"})
        for rule in rules
    )
    codes = {issue.code for issue in validate_rules(broken)}
    assert "ER_UNKNOWN_OBJECT_TYPE" in codes


def test_unknown_search_capability_flagged(rules):
    broken = tuple(
        rule if rule.object_type_id != "sapnexus:Material" else
        type(rule)(**{**rule.__dict__, "search_capability_id": "MD.Ghost.Search"})
        for rule in rules
    )
    codes = {issue.code for issue in validate_rules(broken)}
    assert "ER_UNKNOWN_SEARCH_CAPABILITY" in codes


def test_binding_type_mismatch_flagged(rules):
    broken = tuple(
        rule if rule.object_type_id != "sapnexus:Customer" else
        type(rule)(**{
            **rule.__dict__,
            # SD.SalesOrder.GetList.material is a MaterialNumber slot, not CustomerNumber.
            "parameter_bindings": (
                type(rule.parameter_bindings[0])("SD.SalesOrder.GetList", "material"),
            ),
        })
        for rule in rules
    )
    codes = {issue.code for issue in validate_rules(broken)}
    assert "ER_BINDING_TYPE_MISMATCH" in codes
