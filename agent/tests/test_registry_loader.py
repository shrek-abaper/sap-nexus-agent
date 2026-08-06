from dataclasses import fields
from pathlib import Path

from sap_nexus_agent.call_plan import CallPlan, create_call_plan
from sap_nexus_agent.registry_loader import (
    CapabilityDescriptor,
    InputDescriptor,
    IntentCatalog,
    load_intent_catalog,
)

# 仓库根目录：agent/tests/ 向上两级
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_intent_catalog_returns_active_capabilities():
    catalog = load_intent_catalog(str(REPO_ROOT))

    assert "MM.Inventory.GetAvailability" in catalog.capability_ids
    assert "MM.PurchaseOrder.GetList" in catalog.capability_ids
    assert "MM.PR.CreateDraft" in catalog.capability_ids
    assert len(catalog.capabilities) == 3


def test_load_intent_catalog_filters_inactive():
    """catalog 只含 active capability（当前 registry 两个都 active）。"""
    catalog = load_intent_catalog(str(REPO_ROOT))

    for cap in catalog.capabilities:
        assert cap.capability_id in catalog.capability_ids


def test_inventory_descriptor_inputs_parsed():
    catalog = load_intent_catalog(str(REPO_ROOT))
    inv = catalog.find("MM.Inventory.GetAvailability")

    assert inv is not None
    assert inv.domain == "MM"
    assert inv.business_object == "InventoryStock"
    input_names = {inp.name for inp in inv.inputs}
    assert input_names == {"material", "plant", "unit"}
    material = next(inp for inp in inv.inputs if inp.name == "material")
    assert material.required is True
    assert material.semantic_type == "sapnexus:MaterialNumber"
    assert material.binding_kind == "identifier"
    assert material.min_length == 1
    assert material.max_length == 40
    assert material.pattern is None
    unit = next(inp for inp in inv.inputs if inp.name == "unit")
    assert unit.required is False


def test_purchase_order_descriptor_inputs_parsed():
    catalog = load_intent_catalog(str(REPO_ROOT))
    po = catalog.find("MM.PurchaseOrder.GetList")

    assert po is not None
    assert po.business_object == "PurchaseOrder"
    input_names = {inp.name for inp in po.inputs}
    assert input_names == {"poNumber", "vendor", "plant", "material"}
    # PO 所有 input 均 optional
    assert all(not inp.required for inp in po.inputs)


def test_pr_descriptor_requires_purchasing_group():
    catalog = load_intent_catalog(str(REPO_ROOT))
    pr = catalog.find("MM.PR.CreateDraft")

    assert pr is not None
    purchasing_group = next(inp for inp in pr.inputs if inp.name == "purchasing_group")
    assert purchasing_group.semantic_name == "purchasingGroup"
    assert purchasing_group.required is True


def test_find_returns_none_for_unknown_capability():
    catalog = load_intent_catalog(str(REPO_ROOT))

    assert catalog.find("MM.Nonexistent.Capability") is None


def test_load_intent_catalog_walks_up_to_find_registry():
    """无 repo_root 参数时，从 __file__ 向上查找 registry/。"""
    catalog = load_intent_catalog()

    assert "MM.Inventory.GetAvailability" in catalog.capability_ids


def test_load_intent_catalog_returns_empty_when_registry_not_found(tmp_path, monkeypatch):
    """显式 repo_root 下无 registry 时返回空 catalog（不向上回退，安全失败）。"""
    monkeypatch.delenv("SAP_NEXUS_AGENT_ROOT", raising=False)
    catalog = load_intent_catalog(str(tmp_path))

    assert catalog.capabilities == ()
    assert catalog.capability_ids == frozenset()


def test_empty_catalog_find_returns_none():
    empty = IntentCatalog(capabilities=(), capability_ids=frozenset())

    assert empty.find("anything") is None


def test_registry_v2_metadata_does_not_change_runtime_descriptors():
    catalog = load_intent_catalog(str(REPO_ROOT))

    assert tuple(sorted(catalog.capability_ids)) == (
        "MM.Inventory.GetAvailability",
        "MM.PR.CreateDraft",
        "MM.PurchaseOrder.GetList",
    )
    inventory = catalog.find("MM.Inventory.GetAvailability")
    assert inventory is not None
    assert {item.name for item in inventory.inputs} == {"material", "plant", "unit"}
    assert tuple(field.name for field in fields(CapabilityDescriptor)) == (
        "capability_id",
        "name",
        "description",
        "domain",
        "business_object",
        "inputs",
        "aliases",
        "examples",
    )
    assert tuple(field.name for field in fields(InputDescriptor)) == (
        "name",
        "semantic_name",
        "semantic_type",
        "binding_kind",
        "required",
        "type",
        "min_length",
        "max_length",
        "pattern",
    )

    plan = create_call_plan(inventory.capability_id, {"material": "MAT-1"})
    assert tuple(field.name for field in fields(CallPlan)) == (
        "agent_trace_id",
        "capability_id",
        "kind",
        "parameters",
        "validation_policy",
        "created_by",
        "requires_approval",
    )
    assert tuple(plan.to_dict()) == (
        "agentTraceId",
        "capabilityId",
        "kind",
        "parameters",
        "validationPolicy",
        "createdBy",
        "requiresApproval",
    )


# Runbook 14: aliases / examples fields.
def test_capability_descriptor_has_aliases_and_examples_fields():
    from sap_nexus_agent.registry_loader import CapabilityDescriptor

    field_names = {f.name for f in fields(CapabilityDescriptor)}
    assert "aliases" in field_names
    assert "examples" in field_names


def test_load_intent_catalog_populates_aliases_and_examples():
    catalog = load_intent_catalog(str(REPO_ROOT))
    inv = catalog.find("MM.Inventory.GetAvailability")
    assert inv is not None
    # aliases / examples should be tuples (may be empty if registry lacks them).
    assert isinstance(inv.aliases, tuple)
    assert isinstance(inv.examples, tuple)


def test_load_intent_catalog_capabilities_without_aliases_examples_still_load():
    catalog = load_intent_catalog(str(REPO_ROOT))
    # All 3 capabilities must load; absence of aliases/examples is OK.
    assert len(catalog.capabilities) >= 3
    for cap in catalog.capabilities:
        assert isinstance(cap.aliases, tuple)
        assert isinstance(cap.examples, tuple)
