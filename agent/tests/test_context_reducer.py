import dataclasses
import json
from pathlib import Path

import pytest

from sap_nexus_agent.context_candidates import ContextCandidate, ContextCandidateSet, SlotCandidates
from sap_nexus_agent.context_reducer import ContextReductionRequest, reduce_context
from sap_nexus_agent.read_context import (
    ConversationReadState,
    PendingInteraction,
    ReadContextFrame,
    SlotBinding,
)
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
    explicit: dict[str, str] | None = None,
    confirmations: dict[str, str] | None = None,
    model: dict[str, str] | None = None,
    clear_slots: tuple[str, ...] = (),
) -> ContextCandidateSet:
    deterministic = deterministic or {}
    explicit = explicit or {}
    confirmations = confirmations or {}
    model = model or {}
    slots = {}
    for input_ in descriptor.inputs:
        items = []
        if input_.name in deterministic:
            items.append(
                ContextCandidate(input_.name, deterministic[input_.name], "DETERMINISTIC_LABEL")
            )
        if input_.name in explicit:
            items.append(ContextCandidate(input_.name, explicit[input_.name], "EXPLICIT_CORRECTION"))
        if input_.name in confirmations:
            items.append(ContextCandidate(input_.name, confirmations[input_.name], "CONFIRMATION"))
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
    registry_snapshot_id: str = "snapshot-1",
    capability_version: str = "1",
) -> ContextReductionRequest:
    return ContextReductionRequest(
        prior_state=state,
        candidates=candidate_set,
        descriptor=descriptor,
        registry_snapshot_id=registry_snapshot_id,
        capability_version=capability_version,
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


def test_optional_purchase_order_clear_removes_binding_without_breaking_ready(descriptors):
    purchase_order = descriptors["purchase_order"]
    initial = reduce_context(
        request(
            ConversationReadState(None, None, 0),
            purchase_order,
            candidates(purchase_order, deterministic={"vendor": "1000"}),
            "turn-1",
        )
    )

    result = reduce_context(
        request(
            initial.next_state,
            purchase_order,
            candidates(purchase_order, clear_slots=("vendor",)),
            "turn-2",
        )
    )

    assert result.operation == "CLEAR_SLOT"
    assert result.next_state.active_frame.status == "READY"
    assert "vendor" not in result.next_state.active_frame.slots
    assert "vendor" in result.changed_slots
    assert any(evidence.reason == "optional_slot_cleared" for evidence in result.evidence)


def test_explicit_correction_outranks_competing_deterministic_label(descriptors):
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
            candidates(
                inventory,
                deterministic={"plant": "5100"},
                explicit={"plant": "1000"},
            ),
            "turn-2",
        )
    )

    assert result.operation == "REPLACE_SLOT"
    assert slot(result, "plant").value == "1000"
    assert slot(result, "plant").provenance == "EXPLICIT"
    assert any(evidence.source == "EXPLICIT_CORRECTION" for evidence in result.evidence)


def test_standalone_confirmation_preserves_confirmation_evidence_and_provenance(descriptors):
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
            candidates(inventory, confirmations={"plant": "1000"}),
            "turn-2",
        )
    )

    assert slot(result, "plant").value == "1000"
    assert slot(result, "plant").provenance == "CONFIRMED"
    assert any(evidence.source == "CONFIRMATION" for evidence in result.evidence)
    assert not any(evidence.source == "EXPLICIT_CORRECTION" for evidence in result.evidence)


def test_confirmation_outranks_competing_ordinary_deterministic_syntax(descriptors):
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
            candidates(
                inventory,
                deterministic={"plant": "5100"},
                confirmations={"plant": "1000"},
            ),
            "turn-2",
        )
    )

    assert slot(result, "plant").value == "1000"
    assert slot(result, "plant").provenance == "CONFIRMED"
    assert any(evidence.source == "CONFIRMATION" for evidence in result.evidence)


@pytest.mark.parametrize(
    "slot_name,value",
    (("plant", "工厂"), ("material", "x" * 41)),
)
def test_reducer_rejects_forged_invalid_deterministic_values(descriptors, slot_name, value):
    inventory = descriptors["inventory"]

    result = reduce_context(
        request(
            ConversationReadState(None, None, 0),
            inventory,
            candidates(inventory, deterministic={slot_name: value}),
            "turn-1",
        )
    )

    assert result.next_state.active_frame.status == "COLLECTING"
    assert slot_name not in result.next_state.active_frame.slots
    assert f"invalid_semantic_value:{slot_name}:{value}" in result.issues


def test_snapshot_rebind_requires_current_descriptor_validation(descriptors):
    inventory = descriptors["inventory"]
    initial = reduce_context(
        request(
            ConversationReadState(None, None, 0),
            inventory,
            candidates(inventory, deterministic={"material": "DEMOA2", "plant": "5100"}),
            "turn-1",
        )
    )

    compatible = reduce_context(
        request(
            initial.next_state,
            inventory,
            candidates(inventory),
            "turn-2",
            registry_snapshot_id="snapshot-2",
        )
    )
    assert compatible.next_state.active_frame.status == "READY"
    assert any(evidence.reason == "snapshot_rebound" for evidence in compatible.evidence)

    invalid_plant = SlotBinding(
        name="plant",
        value="工厂",
        candidates=("工厂",),
        state="RESOLVED",
        provenance="EXPLICIT",
        source_turn_id="turn-1",
        source_span=None,
        issues=(),
    )
    incompatible_state = dataclasses.replace(
        initial.next_state,
        active_frame=dataclasses.replace(initial.next_state.active_frame, slots={
            **initial.next_state.active_frame.slots,
            "plant": invalid_plant,
        }),
    )
    incompatible = reduce_context(
        request(
            incompatible_state,
            inventory,
            candidates(inventory),
            "turn-2",
            registry_snapshot_id="snapshot-2",
        )
    )
    assert incompatible.next_state.active_frame.status == "STALE"
    assert "snapshot_revalidation_required" in incompatible.issues


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


def test_fixture_sequences_execute_against_the_pure_reducer(descriptors):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "governed_read_context_cases.json").read_text()
    )

    assert {case["caseId"] for case in fixture["cases"]} == {
        "direct-plant-switch",
        "clear-then-ambiguous-recovery",
    }
    inventory = descriptors["inventory"]
    for case in fixture["cases"]:
        state = ConversationReadState(None, None, 0)
        for turn in case["turns"]:
            candidate_data = turn["candidates"]
            result = reduce_context(
                request(
                    state,
                    inventory,
                    candidates(
                        inventory,
                        deterministic=candidate_data.get("deterministic"),
                        explicit=candidate_data.get("explicit"),
                        model=candidate_data.get("model"),
                        clear_slots=tuple(candidate_data.get("clearSlots", ())),
                    ),
                    turn["turnId"],
                )
            )
            expected = turn["expected"]
            assert result.operation == expected["operation"]
            assert result.next_state.active_frame.status == expected["status"]
            for name, value in expected.get("slots", {}).items():
                if value is None:
                    assert result.next_state.active_frame.slots[name].state == "CLEARED"
                else:
                    assert result.next_state.active_frame.slots[name].value == value
            for issue in expected.get("issues", ()):
                assert issue in result.issues
            state = result.next_state


@pytest.mark.parametrize(
    "descriptor_name,clear_slot,replace_slot,initial_values,replacement_values",
    (
        (
            "inventory",
            "material",
            "plant",
            {"material": "DEMOA2", "plant": "5100"},
            {"material": "M002", "plant": "1000"},
        ),
        (
            "purchase_order",
            "vendor",
            "plant",
            {"poNumber": "4500000001", "vendor": "1000", "plant": "5100", "material": "DEMOA2"},
            {"poNumber": "4500000002", "vendor": "1001", "plant": "1000", "material": "M002"},
        ),
    ),
)
def test_each_read_descriptor_has_fail_closed_slot_operations(
    descriptors, descriptor_name, clear_slot, replace_slot, initial_values, replacement_values
):
    descriptor = descriptors[descriptor_name]
    ready = reduce_context(
        request(ConversationReadState(None, None, 0), descriptor, candidates(descriptor, deterministic=initial_values), "turn-1")
    ).next_state

    cleared = reduce_context(
        request(ready, descriptor, candidates(descriptor, clear_slots=(clear_slot,)), "turn-2")
    )
    assert cleared.operation == "CLEAR_SLOT"
    assert len((cleared.next_state.pending_interaction,)) == 1

    replaced = reduce_context(
        request(ready, descriptor, candidates(descriptor, deterministic={replace_slot: replacement_values[replace_slot]}), "turn-3")
    )
    assert replaced.operation == "REPLACE_SLOT"
    assert slot(replaced, replace_slot).value == replacement_values[replace_slot]

    conflict_base = candidates(descriptor, deterministic={replace_slot: initial_values[replace_slot]})
    conflict_slots = dict(conflict_base.slots)
    conflict_slots[replace_slot] = SlotCandidates(
        replace_slot,
        (
            ContextCandidate(replace_slot, initial_values[replace_slot], "DETERMINISTIC_LABEL"),
            ContextCandidate(replace_slot, replacement_values[replace_slot], "DETERMINISTIC_LABEL"),
        ),
    )
    conflicted = reduce_context(
        request(ready, descriptor, ContextCandidateSet(conflict_slots, (), ()), "turn-4")
    )
    assert conflicted.next_state.active_frame.status == "CONFLICTED"

    pending = PendingInteraction.slot_clarification(
        frame_id=ready.active_frame.frame_id,
        expected_fields=(replace_slot,),
        state_version=ready.state_version,
        registry_snapshot_id="snapshot-1",
        expires_at="2026-08-06T09:15:00Z",
    )
    pending_state = dataclasses.replace(ready, pending_interaction=pending)
    confirmed = reduce_context(
        request(pending_state, descriptor, candidates(descriptor, deterministic={replace_slot: replacement_values[replace_slot]}), "turn-5")
    )
    assert confirmed.operation == "CONFIRM_PENDING"
    assert confirmed.next_state.pending_interaction is None

    expired = dataclasses.replace(
        ready,
        pending_interaction=dataclasses.replace(pending, expires_at="2026-08-06T08:00:00Z"),
    )
    stale = reduce_context(
        request(expired, descriptor, candidates(descriptor, deterministic={replace_slot: replacement_values[replace_slot]}), "turn-6")
    )
    assert stale.operation == "REJECT_PENDING"
    assert stale.next_state.active_frame.status == "COLLECTING"
    assert stale.next_state.pending_interaction is not None

    assert reduce_context(request(ready, descriptor, candidates(descriptor), "turn-7")) == reduce_context(
        request(ready, descriptor, candidates(descriptor), "turn-7")
    )
