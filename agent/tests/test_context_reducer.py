import dataclasses
import json
from pathlib import Path

import pytest

from sap_nexus_agent.context_candidates import ContextCandidate, ContextCandidateSet, SlotCandidates
from sap_nexus_agent.context_reducer import ContextReductionRequest, reduce_context
from sap_nexus_agent.read_context import ConversationReadState, ReadContextFrame, SlotBinding
from sap_nexus_agent.registry_loader import CapabilityDescriptor, load_intent_catalog


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_TIME = "2026-08-06T09:00:00Z"


@pytest.fixture(scope="module")
def descriptors() -> dict[str, CapabilityDescriptor]:
    catalog = load_intent_catalog(str(REPO_ROOT))
    inventory = catalog.find("MM.Inventory.GetAvailability")
    purchase_order = catalog.find("MM.PurchaseOrder.GetList")
    assert inventory is not None
    assert purchase_order is not None
    return {"inventory": inventory, "purchase_order": purchase_order}


def candidates(
    descriptor: CapabilityDescriptor,
    *,
    deterministic: dict[str, str] | None = None,
    model: dict[str, str] | None = None,
    clear_slots: tuple[str, ...] = (),
) -> ContextCandidateSet:
    deterministic = deterministic or {}
    model = model or {}
    slots = {}
    for input_ in descriptor.inputs:
        items = []
        if input_.name in deterministic:
            items.append(
                ContextCandidate(input_.name, deterministic[input_.name], "DETERMINISTIC_LABEL")
            )
        if input_.name in model:
            items.append(ContextCandidate(input_.name, model[input_.name], "MODEL_CANDIDATE"))
        slots[input_.name] = SlotCandidates(input_.name, tuple(items))
    return ContextCandidateSet(slots=slots, clear_slots=clear_slots, discard_reasons=())


def request(
    state: ConversationReadState,
    descriptor: CapabilityDescriptor,
    candidate_set: ContextCandidateSet,
    turn_id: str,
    server_time: str = SERVER_TIME,
) -> ContextReductionRequest:
    return ContextReductionRequest(
        prior_state=state,
        candidates=candidate_set,
        descriptor=descriptor,
        registry_snapshot_id="snapshot-1",
        capability_version="1",
        turn_id=turn_id,
        server_time=server_time,
    )


def slot(resolution, name: str):
    return resolution.next_state.active_frame.slots[name]


def test_clear_then_ambiguous_material_requires_explicit_recovery(descriptors):
    inventory = descriptors["inventory"]
    empty_state = ConversationReadState(active_frame=None, pending_interaction=None, state_version=0)

    turn_1 = reduce_context(
        request(
            empty_state,
            inventory,
            candidates(inventory, deterministic={"material": "DEMOA2", "plant": "5100"}),
            "turn-1",
        )
    )
    assert turn_1.next_state.active_frame.status == "READY"
    assert turn_1.next_state.pending_interaction is None

    turn_2 = reduce_context(
        request(
            turn_1.next_state,
            inventory,
            candidates(inventory, clear_slots=("material",)),
            "turn-2",
        )
    )
    assert turn_2.operation == "CLEAR_SLOT"
    assert slot(turn_2, "material").state == "CLEARED"
    assert slot(turn_2, "plant").value == "5100"
    assert turn_2.next_state.pending_interaction.expected_fields == ("material",)

    turn_3 = reduce_context(
        request(
            turn_2.next_state,
            inventory,
            candidates(
                inventory,
                deterministic={"plant": "1000"},
                model={"material": "1000", "plant": "工厂"},
            ),
            "turn-3",
        )
    )
    assert turn_3.next_state.active_frame.status in {"COLLECTING", "CONFLICTED"}
    assert slot(turn_3, "plant").value == "1000"
    assert slot(turn_3, "material").state != "RESOLVED"
    assert turn_3.next_state.pending_interaction.expected_fields == ("material",)

    turn_4 = reduce_context(
        request(
            turn_3.next_state,
            inventory,
            candidates(
                inventory,
                deterministic={"material": "DEMOA2", "plant": "1000"},
            ),
            "turn-4",
        )
    )
    assert turn_4.operation == "CONFIRM_PENDING"
    assert turn_4.next_state.active_frame.status == "READY"
    assert slot(turn_4, "material").provenance == "CONFIRMED"
    assert slot(turn_4, "plant").provenance == "EXPLICIT"
    assert turn_4.next_state.pending_interaction is None
    assert {name: bound.value for name, bound in turn_4.next_state.active_frame.slots.items() if bound.value} == {
        "material": "DEMOA2",
        "plant": "1000",
    }


def test_direct_plant_switch_inherits_confirmed_material(descriptors):
    inventory = descriptors["inventory"]
    initial = reduce_context(
        request(
            ConversationReadState(None, None, 0),
            inventory,
            candidates(inventory, deterministic={"material": "DEMOA2", "plant": "5100"}),
            "turn-1",
        )
    )

    result = reduce_context(
        request(
            initial.next_state,
            inventory,
            candidates(inventory, deterministic={"plant": "1000"}),
            "turn-2",
        )
    )

    assert result.operation == "REPLACE_SLOT"
    assert result.next_state.active_frame.status == "READY"
    assert slot(result, "material").value == "DEMOA2"
    assert slot(result, "material").provenance == "INHERITED"
    assert slot(result, "plant").value == "1000"
    assert slot(result, "plant").provenance == "EXPLICIT"


def test_model_candidate_cannot_resolve_a_required_slot(descriptors):
    inventory = descriptors["inventory"]

    result = reduce_context(
        request(
            ConversationReadState(None, None, 0),
            inventory,
            candidates(inventory, model={"material": "1000", "plant": "5100"}),
            "turn-1",
        )
    )

    assert result.next_state.active_frame.status == "COLLECTING"
    assert "material" not in result.next_state.active_frame.slots
    assert "plant" not in result.next_state.active_frame.slots
    assert any(evidence.source == "MODEL_CANDIDATE" for evidence in result.evidence)


def test_inherited_legacy_slot_cannot_be_silently_promoted_to_ready(descriptors):
    inventory = descriptors["inventory"]
    legacy_slot = SlotBinding(
        name="material",
        value="DEMOA2",
        candidates=("DEMOA2",),
        state="RESOLVED",
        provenance="INHERITED_LEGACY",
        source_turn_id="legacy-turn",
        source_span=None,
        issues=(),
    )
    plant_slot = SlotBinding(
        name="plant",
        value="5100",
        candidates=("5100",),
        state="RESOLVED",
        provenance="EXPLICIT",
        source_turn_id="turn-1",
        source_span=None,
        issues=(),
    )
    state = ConversationReadState(
        active_frame=ReadContextFrame(
            frame_id="legacy-frame",
            capability_id=inventory.capability_id,
            slots={"material": legacy_slot, "plant": plant_slot},
            status="STALE",
            created_turn_id="legacy-turn",
            updated_turn_id="legacy-turn",
            registry_snapshot_id="snapshot-1",
            capability_version="1",
        ),
        pending_interaction=None,
        state_version=1,
    )

    result = reduce_context(request(state, inventory, candidates(inventory), "turn-2"))

    assert result.next_state.active_frame.status == "STALE"
    assert slot(result, "material").provenance == "INHERITED_LEGACY"


def test_expired_pending_answer_is_discarded_and_reclarified(descriptors):
    inventory = descriptors["inventory"]
    initial = reduce_context(
        request(
            ConversationReadState(None, None, 0),
            inventory,
            candidates(inventory, deterministic={"plant": "5100"}),
            "turn-1",
        )
    )

    result = reduce_context(
        request(
            initial.next_state,
            inventory,
            candidates(inventory, deterministic={"material": "DEMOA2"}),
            "turn-2",
            server_time="2026-08-06T09:16:00Z",
        )
    )

    assert result.operation == "REJECT_PENDING"
    assert result.next_state.active_frame.status == "COLLECTING"
    assert "material" not in result.next_state.active_frame.slots
    assert result.next_state.pending_interaction.expected_fields == ("material",)


def test_capability_switch_archives_active_frame_without_incompatible_inheritance(descriptors):
    inventory = descriptors["inventory"]
    purchase_order = descriptors["purchase_order"]
    inventory_state = reduce_context(
        request(
            ConversationReadState(None, None, 0),
            inventory,
            candidates(inventory, deterministic={"material": "DEMOA2", "plant": "5100"}),
            "turn-1",
        )
    ).next_state

    switched = reduce_context(
        request(
            inventory_state,
            purchase_order,
            candidates(purchase_order, deterministic={"poNumber": "4500000001"}),
            "turn-2",
        )
    )

    assert switched.operation == "SWITCH_CAPABILITY"
    assert switched.next_state.active_frame.capability_id == purchase_order.capability_id
    assert len(switched.next_state.recent_frames) == 1
    assert switched.next_state.recent_frames[0].capability_id == inventory.capability_id
    assert "material" not in switched.next_state.active_frame.slots


@pytest.mark.parametrize("descriptor_name", ("inventory", "purchase_order"))
def test_reduction_is_immutable_and_deterministic_for_each_read_descriptor(descriptors, descriptor_name):
    descriptor = descriptors[descriptor_name]
    values = {
        "material": "DEMOA2",
        "plant": "1000",
        "poNumber": "4500000001",
        "vendor": "1000",
        "unit": "EA",
    }
    candidate_set = candidates(
        descriptor,
        deterministic={input_.name: values[input_.name] for input_ in descriptor.inputs},
    )
    prior = ConversationReadState(None, None, 0)
    first = reduce_context(request(prior, descriptor, candidate_set, "turn-1"))
    replay = reduce_context(request(prior, descriptor, candidate_set, "turn-1"))

    assert prior.active_frame is None
    assert first == replay
    assert first.next_state is not prior
    assert first.next_state.state_version == 1


def test_recent_frames_are_capped_and_legacy_state_keeps_empty_recent_frames(descriptors):
    inventory = descriptors["inventory"]
    purchase_order = descriptors["purchase_order"]
    state = ConversationReadState.from_dict({"activeFrame": None, "pendingInteraction": None, "stateVersion": 0})
    assert state.recent_frames == ()

    for number, descriptor in enumerate((inventory, purchase_order, inventory, purchase_order), start=1):
        result = reduce_context(
            request(
                state,
                descriptor,
                candidates(descriptor, deterministic={"plant": f"F10{number}"}),
                f"turn-{number}",
            )
        )
        state = result.next_state

    assert len(state.recent_frames) == 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.recent_frames = ()


def test_fixture_declares_direct_switch_and_explicit_recovery_sequences():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "governed_read_context_cases.json").read_text()
    )

    assert {case["caseId"] for case in fixture["cases"]} == {
        "direct-plant-switch",
        "clear-then-ambiguous-recovery",
    }
    assert fixture["cases"][1]["turns"][-1]["turnId"] == "turn-4"
