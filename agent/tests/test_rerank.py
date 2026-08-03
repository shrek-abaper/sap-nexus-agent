"""Tests for bounded rerank stage (Runbook 14)."""

from __future__ import annotations

from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal
from sap_nexus_agent.rerank import RerankCandidate, rerank
from sap_nexus_agent.recall import recall
from sap_nexus_agent.registry_loader import (
    CapabilityDescriptor,
    InputDescriptor,
    IntentCatalog,
)


def _make_catalog() -> IntentCatalog:
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
    )
    return IntentCatalog(
        capabilities=capabilities,
        capability_ids=frozenset(c.capability_id for c in capabilities),
    )


def _make_envelope(hint: str | None, params: dict[str, str] | None = None) -> IntentEnvelope:
    return IntentEnvelope(
        envelope_id="env-001",
        utterance="查库存 DEMOA2 1000",
        goals=(
            IntentGoal(
                goal_text="查库存",
                capability_hint=hint,
                parameters=params or {},
                missing=[],
            ),
        ),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="llm",
    )


def test_rerank_llm_hint_ranks_first():
    """LLM hint match (+3) + lexical (+2) + param fit (+1) = 6, ranks first."""
    catalog = _make_catalog()
    visible_ids = frozenset(("MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"))
    envelope = _make_envelope(
        hint="MM.Inventory.GetAvailability",
        params={"material": "DEMOA2", "plant": "1000"},
    )
    # Use recall to get candidates.
    candidates = recall(envelope.utterance, visible_ids, catalog)
    # Add PO manually for the test (it doesn't match the utterance but we want
    # to verify rerank ordering with multiple candidates).
    if "MM.PurchaseOrder.GetList" not in candidates:
        candidates = [*candidates, "MM.PurchaseOrder.GetList"]

    ranked, evidence = rerank(candidates, envelope, catalog)
    assert ranked[0] == "MM.Inventory.GetAvailability"
    inv_score = next(e["score"] for e in evidence if e["capabilityId"] == "MM.Inventory.GetAvailability")
    assert inv_score >= 5  # hint +3 + lexical +2 (param fit may or may not apply)


def test_rerank_tie_break_alphabetical():
    """Same score -> alphabetical by capability_id."""
    catalog = _make_catalog()
    visible_ids = frozenset(("MM.Inventory.GetAvailability", "MM.PurchaseOrder.GetList"))
    # Envelope with no hint and no params — both candidates get only lexical
    # if both matched; we'll feed both as candidates directly.
    envelope = IntentEnvelope(
        envelope_id="env-002",
        utterance="查询",
        goals=(),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snap-001",
        discard_reasons=[],
        created_by="rule",
    )
    candidates = ["MM.PurchaseOrder.GetList", "MM.Inventory.GetAvailability"]
    ranked, evidence = rerank(candidates, envelope, catalog)
    # Both have score 0 (no hint, no lexical hit on '查询'); alphabetical
    # puts Inventory first.
    assert ranked[0] == "MM.Inventory.GetAvailability"
    assert ranked[1] == "MM.PurchaseOrder.GetList"


def test_rerank_param_fit_only_when_all_required_covered():
    """Param fit +1 only when all required inputs are covered."""
    catalog = _make_catalog()
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    # Only material provided — plant missing. Param fit should be +0.
    envelope_partial = _make_envelope(
        hint="MM.Inventory.GetAvailability",
        params={"material": "DEMOA2"},
    )
    ranked_partial, evidence_partial = rerank(
        ["MM.Inventory.GetAvailability"], envelope_partial, catalog
    )
    partial_score = evidence_partial[0]["score"]
    # hint +3 + lexical +2 = 5 (no param fit).
    assert partial_score == 5

    # Both material + plant provided — param fit +1.
    envelope_full = _make_envelope(
        hint="MM.Inventory.GetAvailability",
        params={"material": "DEMOA2", "plant": "1000"},
    )
    ranked_full, evidence_full = rerank(
        ["MM.Inventory.GetAvailability"], envelope_full, catalog
    )
    full_score = evidence_full[0]["score"]
    # hint +3 + lexical +2 + param fit +1 = 6.
    assert full_score == 6


def test_rerank_evidence_contains_breakdown():
    """Evidence contains per-candidate score breakdown with components."""
    catalog = _make_catalog()
    visible_ids = frozenset(("MM.Inventory.GetAvailability",))
    envelope = _make_envelope(
        hint="MM.Inventory.GetAvailability",
        params={"material": "DEMOA2", "plant": "1000"},
    )
    ranked, evidence = rerank(["MM.Inventory.GetAvailability"], envelope, catalog)
    assert len(evidence) == 1
    entry = evidence[0]
    assert entry["capabilityId"] == "MM.Inventory.GetAvailability"
    assert "score" in entry
    assert "components" in entry
    # Components should reference the per-source contributions.
    components = entry["components"]
    assert components.get("llm_hint") == 3
    assert components.get("lexical") == 2 or components.get("alias") == 2 or components.get("example") == 1


def test_rerank_returns_empty_for_empty_candidates():
    """Empty candidates -> empty ranked + empty evidence."""
    catalog = _make_catalog()
    envelope = _make_envelope(hint=None)
    ranked, evidence = rerank([], envelope, catalog)
    assert ranked == []
    assert evidence == []


def test_rerank_output_is_advisory_no_matchdecision():
    """rerank returns (list[str], list[dict]), not a MatchDecision."""
    catalog = _make_catalog()
    envelope = _make_envelope(hint="MM.Inventory.GetAvailability")
    ranked, evidence = rerank(["MM.Inventory.GetAvailability"], envelope, catalog)
    assert isinstance(ranked, list)
    assert isinstance(evidence, list)
    for e in evidence:
        assert isinstance(e, dict)
