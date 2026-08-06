from pathlib import Path

import pytest

from sap_nexus_agent.context_candidates import extract_context_candidates
from sap_nexus_agent.intent_envelope import IntentEnvelope, IntentGoal
from sap_nexus_agent.registry_loader import load_intent_catalog


REPO_ROOT = Path(__file__).resolve().parents[2]


def inventory_descriptor():
    descriptor = load_intent_catalog(str(REPO_ROOT)).find("MM.Inventory.GetAvailability")
    assert descriptor is not None
    return descriptor


def purchase_order_descriptor():
    descriptor = load_intent_catalog(str(REPO_ROOT)).find("MM.PurchaseOrder.GetList")
    assert descriptor is not None
    return descriptor


def model_envelope(parameters=None, *, discard_reasons=()):
    return IntentEnvelope(
        envelope_id="envelope-1",
        utterance="查库存",
        goals=(
            IntentGoal(
                goal_text="查库存",
                capability_hint="MM.Inventory.GetAvailability",
                parameters=parameters or {},
                missing=[],
            ),
        ),
        user_constraints={},
        ambiguities=[],
        reference_turn_id=None,
        model_evidence={},
        snapshot_id="snapshot-1",
        discard_reasons=list(discard_reasons),
        created_by="llm",
    )


def test_f101_followed_by_plant_is_a_deterministic_plant_candidate():
    candidates = extract_context_candidates(
        "查下这个物料 1000 工厂库存",
        inventory_descriptor(),
        model_envelope({"material": "1000", "plant": "工厂"}),
    )

    assert candidates.for_slot("plant").deterministic_values == ("1000",)
    assert candidates.for_slot("material").model_values == ("1000",)
    assert "invalid_semantic_value:plant:工厂" in candidates.discard_reasons


def test_model_candidate_alone_cannot_be_marked_explicit():
    candidates = extract_context_candidates(
        "查库存", inventory_descriptor(), model_envelope({"material": "1000"})
    )

    assert candidates.for_slot("material").sources == ("MODEL_CANDIDATE",)


def test_labeled_plant_wording_produces_deterministic_candidate():
    candidates = extract_context_candidates("工厂 1000", inventory_descriptor(), None)

    assert candidates.for_slot("plant").deterministic_values == ("1000",)


def test_correction_wording_produces_deterministic_candidate():
    candidates = extract_context_candidates("工厂改成 1000", inventory_descriptor(), None)

    assert candidates.for_slot("plant").deterministic_values == ("1000",)


def test_material_correction_wording_produces_deterministic_candidate():
    candidates = extract_context_candidates("物料改成 M001", inventory_descriptor(), None)

    assert candidates.for_slot("material").deterministic_values == ("M001",)


def test_explicit_confirmation_binds_each_labeled_value_deterministically():
    candidates = extract_context_candidates(
        "这个物料是指上面的 DEMOA2，1000 是工厂", inventory_descriptor(), None
    )

    assert candidates.for_slot("material").deterministic_values == ("DEMOA2",)
    assert candidates.for_slot("plant").deterministic_values == ("1000",)


@pytest.mark.parametrize(
    "utterance,source",
    (
        ("工厂改成 1000", "EXPLICIT_CORRECTION"),
        ("物料是指 DEMOA2", "EXPLICIT_CORRECTION"),
        ("对，就是物料 DEMOA2", "CONFIRMATION"),
    ),
)
def test_correction_and_confirmation_sources_are_distinguished(utterance, source):
    candidates = extract_context_candidates(utterance, inventory_descriptor(), None)

    assert source in candidates.for_slot("material").sources + candidates.for_slot("plant").sources


def test_change_material_only_marks_the_slot_for_clearance():
    candidates = extract_context_candidates("换个物料", inventory_descriptor(), None)

    assert candidates.clear_slots == ("material",)
    assert candidates.for_slot("material").values == ()


def test_technical_model_field_is_discarded_without_creating_a_candidate():
    candidates = extract_context_candidates(
        "查库存",
        inventory_descriptor(),
        model_envelope({"material": "M001", "rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"}),
    )

    assert candidates.for_slot("material").model_values == ("M001",)
    assert "technical_field:rfcName" in candidates.discard_reasons
    assert candidates.for_slot("rfcName").values == ()


def test_generic_semantic_label_extracts_purchase_order_vendor_deterministically():
    candidates = extract_context_candidates("供应商 1000 的采购订单", purchase_order_descriptor(), None)

    assert candidates.for_slot("vendor").deterministic_values == ("1000",)
    assert candidates.for_slot("poNumber").values == ()


def test_generic_semantic_adjacency_extracts_purchase_order_number_deterministically():
    candidates = extract_context_candidates("4500000001 采购订单", purchase_order_descriptor(), None)

    assert candidates.for_slot("poNumber").deterministic_values == ("4500000001",)


def test_constructed_envelope_discards_governance_authority_fields():
    candidates = extract_context_candidates(
        "查库存",
        inventory_descriptor(),
        model_envelope({"material": "M001", "approvalRecord": "approved", "principal": "admin"}),
    )

    assert candidates.for_slot("material").model_values == ("M001",)
    assert "governance_field:approvalRecord" in candidates.discard_reasons
    assert "governance_field:principal" in candidates.discard_reasons
