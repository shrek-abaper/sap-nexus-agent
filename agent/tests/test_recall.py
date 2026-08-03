"""Tests for closed-set recall stage (Runbook 14)."""

from __future__ import annotations

from sap_nexus_agent.recall import recall
from sap_nexus_agent.registry_loader import (
    CapabilityDescriptor,
    InputDescriptor,
    IntentCatalog,
)


def _make_catalog() -> IntentCatalog:
    """Build a minimal catalog with aliases/examples for recall tests."""
    capabilities = (
        CapabilityDescriptor(
            capability_id="MM.Inventory.GetAvailability",
            name="Inventory Availability 库存",
            description="Read material availability for a plant.",
            domain="MM",
            business_object="InventoryStock",
            inputs=(
                InputDescriptor(name="material", semantic_name="material", required=True, type="string"),
                InputDescriptor(name="plant", semantic_name="plant", required=True, type="string"),
            ),
            aliases=("库存查询", "物料可用量"),
            examples=("查物料 DEMOA2 在 1000 工厂的库存",),
        ),
        CapabilityDescriptor(
            capability_id="MM.PurchaseOrder.GetList",
            name="Purchase Order List 采购订单",
            description="Read purchase order list.",
            domain="MM",
            business_object="PurchaseOrder",
            inputs=(
                InputDescriptor(name="poNumber", semantic_name="poNumber", required=False, type="string"),
            ),
            aliases=("PO", "采购订单查询"),
            examples=("查采购订单 4500000001",),
        ),
        CapabilityDescriptor(
            capability_id="MM.PR.CreateDraft",
            name="Purchase Requisition Create Draft 采购申请",
            description="创建采购申请 (PR) 草稿.",
            domain="MM",
            business_object="PurchaseRequisition",
            inputs=(
                InputDescriptor(name="material", semantic_name="material", required=True, type="string"),
            ),
            aliases=("建PR",),
            examples=("帮我建一个采购申请 DEMOA2 1000 100 EA",),
        ),
    )
    return IntentCatalog(
        capabilities=capabilities,
        capability_ids=frozenset(c.capability_id for c in capabilities),
    )


def test_lexical_recall_matches_capability_name():
    """Utterance containing '库存' matches Inventory via name/description."""
    catalog = _make_catalog()
    visible_ids = frozenset(
        ("MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList", "MM.PR.CreateDraft")
    )
    candidates = recall("查库存", visible_ids, catalog)
    assert "MM.Inventory.GetAvailability" in candidates


def test_alias_recall_matches_capability_alias():
    """Utterance containing 'PO' matches PurchaseOrder via alias."""
    catalog = _make_catalog()
    visible_ids = frozenset(
        ("MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList", "MM.PR.CreateDraft")
    )
    candidates = recall("查 PO", visible_ids, catalog)
    assert "MM.PurchaseOrder.GetList" in candidates


def test_example_recall_matches_capability_example():
    """Utterance resembling a registered example matches that capability."""
    catalog = _make_catalog()
    visible_ids = frozenset(
        ("MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList", "MM.PR.CreateDraft")
    )
    # Substring of an example should match.
    candidates = recall("帮我建一个采购申请", visible_ids, catalog)
    assert "MM.PR.CreateDraft" in candidates


def test_recall_dedupes_by_capability_id():
    """Same capability matched via lexical + alias appears only once."""
    catalog = _make_catalog()
    visible_ids = frozenset(
        ("MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList", "MM.PR.CreateDraft")
    )
    # '库存' is in both name and aliases; should dedupe to a single entry.
    candidates = recall("库存查询", visible_ids, catalog)
    assert candidates.count("MM.Inventory.GetAvailability") == 1


def test_recall_filters_to_visible_capability_set():
    """Capabilities not in visible_capability_set are excluded."""
    catalog = _make_catalog()
    # Only Inventory is visible.
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    candidates = recall("采购订单", visible_ids, catalog)
    # PO should NOT appear despite matching, because it's not visible.
    assert "MM.PurchaseOrder.GetList" not in candidates
    assert "MM.Inventory.GetAvailability" not in candidates


def test_recall_returns_empty_for_no_match():
    """Utterance matching nothing returns empty list."""
    catalog = _make_catalog()
    visible_ids = frozenset(
        ("MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList", "MM.PR.CreateDraft")
    )
    candidates = recall("完全无关的查询 xyz123", visible_ids, catalog)
    assert candidates == []


def test_recall_returns_list_of_str():
    """Recall returns list[str], not MatchDecision."""
    catalog = _make_catalog()
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    candidates = recall("库存", visible_ids, catalog)
    assert isinstance(candidates, list)
    for c in candidates:
        assert isinstance(c, str)
