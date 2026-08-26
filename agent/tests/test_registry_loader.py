from dataclasses import fields
from pathlib import Path

from sap_nexus_agent.call_plan import CallPlan, create_call_plan
from sap_nexus_agent.registry_loader import (
    CapabilityDescriptor,
    ConditionConfig,
    InputDescriptor,
    IntentCatalog,
    load_intent_catalog,
)

# 仓库根目录：agent/tests/ 向上两级
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_intent_catalog_returns_active_capabilities():
    catalog = load_intent_catalog(str(REPO_ROOT))

    # R5 — the spec clause requires this asserted "against the Registry content
    # rather than a hardcoded number", so the expected set is read from
    # registry/capabilities.yaml. A hardcoded 4 passes whether or not the loader
    # actually reflects the registry, and silently becomes wrong when a fifth
    # capability is registered.
    import yaml

    declared = yaml.safe_load(
        (REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
    )
    expected_active = {
        capability["capabilityId"]
        for capability in declared["capabilities"]
        if capability.get("status") == "active"
    }
    assert expected_active  # non-vacuity: the registry declares active capabilities
    assert set(catalog.capability_ids) == expected_active
    assert len(catalog.capabilities) == len(expected_active)


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
    assert inv.side_effect == "none"
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
    assert input_names == {"poNumber", "vendor", "plant", "material", "createdSince", "openOnly"}
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
        "MM.Material.GetInfo",
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
        "side_effect",
        "narrative",
        "intent_config",
    )
    assert inventory.narrative is not None
    assert inventory.narrative.fact_shape == "single-value"
    assert inventory.narrative.detail_formatter == "mrp-table"
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
        "extraction",
        "binding",
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


def test_load_intent_catalog_pairs_declarations_with_catalog_atomically():
    catalog = load_intent_catalog()
    pr = catalog.find("MM.PR.CreateDraft")
    assert pr is not None and pr.intent_config is not None
    assert pr.intent_config.intent_name == "pr_create"
    inputs = {i.name: i for i in pr.inputs}
    assert inputs["cost_center"].extraction is not None
    assert inputs["cost_center"].extraction.required_when == ConditionConfig(
        field="acct_assgn_cat", equals="K")
    material_entry = catalog.semantic_types.find("MaterialNumber")
    assert material_entry is not None
    assert material_entry.filters.to_upper_compare is True
    assert material_entry.filters.min_length == 5
    # same call returned both artifacts
    assert {e.entry_id for e in catalog.semantic_types.entries} >= {
        "Plant", "MaterialNumber", "Quantity", "Unit", "Date",
        "PurchasingGroup", "Vendor", "PONumber"}


def test_load_intent_catalog_without_catalog_file_degrades(tmp_path, monkeypatch):
    # capabilities.yaml present, semantic-types.yaml absent -> capabilities still load
    # (loader resolves <root>/registry/capabilities.yaml for SAP_NEXUS_AGENT_ROOT)
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    (registry_dir / "capabilities.yaml").write_text(
        "version: 2\ncapabilities: []\n", encoding="utf-8")
    monkeypatch.setenv("SAP_NEXUS_AGENT_ROOT", str(tmp_path))
    catalog = load_intent_catalog()
    assert catalog.capabilities == ()
    assert catalog.semantic_types.entries == ()


def test_parse_matcher_accepts_named_kind_fields():
    from sap_nexus_agent.registry_loader import _parse_matcher

    prefixed = _parse_matcher({"kind": "prefixed", "prefix": ["在"], "valueShape": "plantCode"})
    assert prefixed is not None
    assert prefixed.prefix == ("在",)
    assert prefixed.value_shape == "plantCode"
    assert prefixed.pattern is None

    regex = _parse_matcher({"kind": "regex", "pattern": "x", "justification": "why"})
    assert regex is not None and regex.justification == "why"


def test_catalog_value_shapes_parsed_from_document():
    from sap_nexus_agent.registry_loader import _parse_semantic_type_catalog

    catalog = _parse_semantic_type_catalog({
        "valueShapes": {"plantCode": "^[A-Z0-9]{4}$"},
        "semanticTypes": [{
            "id": "X",
            "priority": 1,
            "matchers": [{"kind": "valueShape", "valueShape": "plantCode"}],
        }],
    })
    assert catalog.value_shapes == {"plantCode": "^[A-Z0-9]{4}$"}
    assert catalog.find("X") is not None
    assert catalog.find("X").matchers[0].value_shape == "plantCode"
