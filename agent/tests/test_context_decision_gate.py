import dataclasses
import inspect
import pickle
from collections.abc import Mapping
from pathlib import Path

import pytest

from sap_nexus_agent.context_reducer import ContextResolution
from sap_nexus_agent.governed_context import (
    GovernedContext,
    SnapshotLease,
    TrustedPrincipal,
)
from sap_nexus_agent.read_context import ConversationReadState, ReadContextFrame, SlotBinding

from sap_nexus_agent.context_decision_gate import (
    ReadCapabilityCandidates,
    decide_read_context,
)
from sap_nexus_agent.semantic_planning import (
    SemanticSourceDocuments,
    build_registry_snapshot,
    load_semantic_sources,
)


INVENTORY_ID = "MM.Inventory.GetAvailability"
PURCHASE_ORDER_ID = "MM.PurchaseOrder.GetList"
REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_SOURCES = load_semantic_sources(REPO_ROOT)
BASE_SNAPSHOT = build_registry_snapshot(BASE_SOURCES)
SNAPSHOT_ID = BASE_SNAPSHOT.snapshot_id


def _slot(name: str, value: str) -> SlotBinding:
    return SlotBinding(
        name=name,
        value=value,
        candidates=(value,),
        state="RESOLVED",
        provenance="EXPLICIT",
        source_turn_id="turn-1",
        source_span=None,
        issues=(),
    )


def _resolution(
    status: str = "READY", *, snapshot_id: str = SNAPSHOT_ID
) -> ContextResolution:
    frame = ReadContextFrame(
        frame_id="inventory:turn-1",
        capability_id=INVENTORY_ID,
        slots={
            "material": _slot("material", "DEMOA2"),
            "plant": _slot("plant", "1000"),
        },
        status=status,
        created_turn_id="turn-1",
        updated_turn_id="turn-1",
        registry_snapshot_id=snapshot_id,
        capability_version="1",
    )
    return ContextResolution(
        next_state=ConversationReadState(frame, None, 1),
        operation="CONTINUE_FRAME",
        changed_slots=(),
        issues=(),
        evidence=(),
    )


def _candidates(
    *capability_ids: str,
    purpose: str = "AMBIGUITY",
    snapshot_id: str = SNAPSHOT_ID,
) -> ReadCapabilityCandidates:
    return ReadCapabilityCandidates(
        capability_ids=capability_ids,
        snapshot_id=snapshot_id,
        purpose=purpose,
    )


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _sources(
    *,
    capabilities: tuple[dict[str, object], ...] | list[dict[str, object]] | None = None,
    bindings: tuple[dict[str, object], ...] | list[dict[str, object]] | None = None,
) -> SemanticSourceDocuments:
    capabilities_document = _thaw(BASE_SOURCES.capabilities)
    bindings_document = _thaw(BASE_SOURCES.executor_bindings)
    if capabilities is not None:
        capabilities_document["capabilities"] = list(capabilities)
    if bindings is not None:
        bindings_document["bindings"] = list(bindings)
    return SemanticSourceDocuments(
        capabilities=capabilities_document,
        executor_bindings=bindings_document,
        fact_types=BASE_SOURCES.fact_types,
        relations=BASE_SOURCES.relations,
    )


def _malformed_read_sources(mutation: str) -> SemanticSourceDocuments:
    capabilities = _thaw(BASE_SOURCES.capabilities)["capabilities"]
    inventory = next(
        capability
        for capability in capabilities
        if capability["capabilityId"] == INVENTORY_ID
    )
    if mutation == "missing-governance":
        inventory.pop("governance")
    elif mutation == "non-mapping-governance":
        inventory["governance"] = "request-controlled"
    elif mutation.startswith("missing-governance-"):
        inventory["governance"].pop(mutation.removeprefix("missing-governance-"))
    elif mutation == "action-with-read-governance":
        inventory["kind"] = "Action"
    elif mutation == "missing-input-required":
        inventory["inputs"][0].pop("required")
    elif mutation == "invalid-input-required":
        inventory["inputs"][0]["required"] = "false"
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    return _sources(capabilities=capabilities)


def _trusted_run_context(
    sources: SemanticSourceDocuments = BASE_SOURCES,
) -> tuple[GovernedContext, SnapshotLease]:
    snapshot = build_registry_snapshot(sources)
    principal = TrustedPrincipal(
        principal_id="user-1",
        role="operator",
        data_scope={"tenantId": "default"},
    )
    return (
        GovernedContext(
            principal=principal,
            scopes=("tenantId:default",),
            snapshot_id=snapshot.snapshot_id,
            registry_version=snapshot.snapshot_version,
        ),
        SnapshotLease(snapshot=snapshot, sources=sources),
    )


def _decide(
    resolution: ContextResolution | None = None,
    *,
    sources: SemanticSourceDocuments = BASE_SOURCES,
    candidate_ids: tuple[str, ...] | None = None,
    purpose: str = "AMBIGUITY",
):
    governed_context, lease = _trusted_run_context(sources)
    candidates = (
        _candidates(
            *candidate_ids,
            purpose=purpose,
            snapshot_id=lease.snapshot_id,
        )
        if candidate_ids is not None
        else None
    )
    return decide_read_context(
        resolution or _resolution(snapshot_id=lease.snapshot_id),
        governed_context=governed_context,
        lease=lease,
        capability_candidates=candidates,
    )


def test_missing_execution_authority_never_falls_back_to_card_labels() -> None:
    result = decide_read_context(_resolution())

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "EXECUTION_VISIBILITY_INVALID"


def test_trusted_service_derives_authority_and_exposes_no_projection_input() -> None:
    governed_context, lease = _trusted_run_context()

    result = decide_read_context(
        _resolution(snapshot_id=lease.snapshot_id),
        governed_context=governed_context,
        lease=lease,
    )

    assert result.decision.decision_type == "SELECT"
    assert "execution_visibility" not in inspect.signature(
        decide_read_context
    ).parameters


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-governance",
        "non-mapping-governance",
        "missing-governance-sideEffect",
        "missing-governance-requiresApproval",
        "missing-governance-approvalPolicy",
        "missing-governance-dataClassification",
        "missing-governance-auditRequired",
        "action-with-read-governance",
        "missing-input-required",
        "invalid-input-required",
    ],
)
def test_malformed_registry_contract_never_grants_read_authority(
    mutation: str,
) -> None:
    result = _decide(sources=_malformed_read_sources(mutation))

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "EXECUTION_VISIBILITY_INVALID"
    assert result.call_plan_parameters is None


def test_semantic_validation_exception_fails_closed(monkeypatch) -> None:
    from sap_nexus_agent.semantic_planning import validation as semantic_validation

    def fail_validation(_sources):
        raise RuntimeError("validation unavailable")

    monkeypatch.setattr(
        semantic_validation, "build_semantic_contracts", fail_validation
    )

    result = _decide()

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "EXECUTION_VISIBILITY_INVALID"


def test_authority_projection_exception_fails_closed(monkeypatch) -> None:
    from sap_nexus_agent import context_decision_gate

    def fail_projection(*_args, **_kwargs):
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(
        context_decision_gate, "_unique_registry_index", fail_projection
    )

    result = _decide()

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "EXECUTION_VISIBILITY_INVALID"


def test_server_read_authority_is_ephemeral_and_absent_from_result(
    monkeypatch,
) -> None:
    from sap_nexus_agent import context_decision_gate

    captured = []
    original_decide = context_decision_gate._decide_read_context

    def capture_authority(resolution, *, authority, capability_candidates):
        captured.append(authority)
        return original_decide(
            resolution,
            authority=authority,
            capability_candidates=capability_candidates,
        )

    monkeypatch.setattr(
        context_decision_gate, "_decide_read_context", capture_authority
    )

    result = _decide()

    assert result.decision.decision_type == "SELECT"
    assert len(captured) == 1
    authority = captured[0]
    with pytest.raises(TypeError, match="not serializable"):
        pickle.dumps(authority)
    assert INVENTORY_ID not in repr(authority)
    assert SNAPSHOT_ID not in repr(authority)
    assert all(
        getattr(result, field.name) is not authority
        for field in dataclasses.fields(result)
    )


@pytest.mark.parametrize("status", ["COLLECTING", "CONFLICTED", "STALE"])
def test_non_ready_frame_cannot_select(status: str) -> None:
    result = _decide(_resolution(status))

    assert result.decision.decision_type != "SELECT"
    assert result.call_plan_parameters is None


def test_ready_frame_uses_only_resolved_slots() -> None:
    result = _decide()

    assert result.decision.decision_type == "SELECT"
    assert result.decision.parameters == {"material": "DEMOA2", "plant": "1000"}
    assert result.call_plan_parameters == {"material": "DEMOA2", "plant": "1000"}


def test_current_snapshot_and_read_visibility_are_required() -> None:
    result = _decide(_resolution(snapshot_id="sha256:drifted"))

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "CONTEXT_SNAPSHOT_DRIFT"
    assert result.call_plan_parameters is None


def test_non_execution_card_cannot_enter_read_selection() -> None:
    capabilities = _thaw(BASE_SOURCES.capabilities)["capabilities"]
    inventory = next(
        capability
        for capability in capabilities
        if capability["capabilityId"] == INVENTORY_ID
    )
    inventory["governance"]["dataClassification"] = "restricted"
    result = _decide(sources=_sources(capabilities=capabilities))

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


def test_one_current_visible_read_candidate_preserves_single_frame_selection() -> None:
    result = _decide(candidate_ids=(INVENTORY_ID,))

    assert result.decision.decision_type == "SELECT"


def test_trusted_sources_can_prove_a_bound_dry_run_card() -> None:
    result = _decide(candidate_ids=(INVENTORY_ID,))

    assert result.decision.decision_type == "SELECT"


def test_governed_context_with_changed_snapshot_fails_closed() -> None:
    governed_context, lease = _trusted_run_context()
    governed_context = dataclasses.replace(
        governed_context, snapshot_id="sha256:forged"
    )
    result = decide_read_context(
        _resolution(),
        governed_context=governed_context,
        lease=lease,
        capability_candidates=_candidates(INVENTORY_ID),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "EXECUTION_VISIBILITY_INVALID"
    assert result.call_plan_parameters is None


def test_governed_context_cannot_cross_registry_versions() -> None:
    governed_context, lease = _trusted_run_context()
    governed_context = dataclasses.replace(
        governed_context,
        registry_version=governed_context.registry_version + 1,
    )
    result = decide_read_context(
        _resolution(),
        governed_context=governed_context,
        lease=lease,
        capability_candidates=_candidates(INVENTORY_ID),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "EXECUTION_VISIBILITY_INVALID"
    assert result.call_plan_parameters is None


def test_lease_snapshot_must_be_rebuilt_from_the_same_current_sources() -> None:
    governed_context, _ = _trusted_run_context()
    capabilities = _thaw(BASE_SOURCES.capabilities)["capabilities"]
    inventory = next(
        capability
        for capability in capabilities
        if capability["capabilityId"] == INVENTORY_ID
    )
    inventory["description"] = "request-controlled replacement"
    mismatched_lease = SnapshotLease(
        snapshot=BASE_SNAPSHOT,
        sources=_sources(capabilities=capabilities),
    )

    result = decide_read_context(
        _resolution(),
        governed_context=governed_context,
        lease=mismatched_lease,
        capability_candidates=_candidates(INVENTORY_ID),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "EXECUTION_VISIBILITY_INVALID"


def test_trusted_authority_cannot_be_expanded_with_unproven_ids() -> None:
    result = _decide(
        candidate_ids=(INVENTORY_ID, "MM.Inventory.Hidden"),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


def test_raw_execution_id_set_is_not_an_authority_override() -> None:
    _, lease = _trusted_run_context()
    result = decide_read_context(
        _resolution(),
        governed_context=frozenset({INVENTORY_ID}),  # type: ignore[arg-type]
        lease=lease,
        capability_candidates=_candidates(INVENTORY_ID),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "EXECUTION_VISIBILITY_INVALID"
    assert result.call_plan_parameters is None


def test_malformed_trusted_context_fails_closed() -> None:
    _, lease = _trusted_run_context()
    result = decide_read_context(
        _resolution(),
        governed_context="request-controlled",  # type: ignore[arg-type]
        lease=lease,
        capability_candidates=_candidates(INVENTORY_ID),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.decision.error_type == "EXECUTION_VISIBILITY_INVALID"
    assert result.call_plan_parameters is None


@pytest.mark.parametrize(
    "duplicate",
    [
        {
            "bindingId": "inventory-binding",
            "type": "JCO_RFC",
            "constraints": {"sideEffect": "sap_write"},
        },
        {
            "bindingId": "inventory-binding",
            "type": "ODATA",
            "constraints": {"sideEffect": "none"},
        },
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_binding_ids_never_grant_shadow_selection(
    duplicate: dict[str, object], reverse: bool
) -> None:
    bindings = _thaw(BASE_SOURCES.executor_bindings)["bindings"]
    read_binding = next(
        binding
        for binding in bindings
        if binding["bindingId"] == "sap.mm.inventory.md04-stock-req-list"
    )
    duplicate = {
        **duplicate,
        "bindingId": read_binding["bindingId"],
    }
    others = [binding for binding in bindings if binding is not read_binding]
    duplicated = (
        [duplicate, read_binding, *others]
        if reverse
        else [read_binding, duplicate, *others]
    )
    result = _decide(
        sources=_sources(bindings=duplicated),
        candidate_ids=(INVENTORY_ID,),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_capability_ids_never_grant_shadow_options(reverse: bool) -> None:
    capabilities = _thaw(BASE_SOURCES.capabilities)["capabilities"]
    inventory = next(
        capability
        for capability in capabilities
        if capability["capabilityId"] == INVENTORY_ID
    )
    duplicate = _thaw(inventory)
    duplicate["executorBinding"] = {
        "type": "ODATA",
        "bindingId": "sap.mm.purchaseorder.list-odata",
    }
    others = [capability for capability in capabilities if capability is not inventory]
    duplicated = (
        [duplicate, inventory, *others]
        if reverse
        else [inventory, duplicate, *others]
    )
    result = _decide(
        sources=_sources(capabilities=duplicated),
        candidate_ids=(INVENTORY_ID, PURCHASE_ORDER_ID),
    )

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


@pytest.mark.parametrize(
    ("candidates", "duplicate_source"),
    [
        ((INVENTORY_ID, INVENTORY_ID), None),
        (("MM.Inventory.Hidden",), None),
        ((INVENTORY_ID,), "duplicate"),
    ],
)
def test_duplicate_or_invisible_candidates_fail_closed(
    candidates, duplicate_source
) -> None:
    sources = BASE_SOURCES
    if duplicate_source == "duplicate":
        capabilities = _thaw(BASE_SOURCES.capabilities)["capabilities"]
        inventory = next(
            capability
            for capability in capabilities
            if capability["capabilityId"] == INVENTORY_ID
        )
        capabilities.append(_thaw(inventory))
        sources = _sources(capabilities=capabilities)
    result = _decide(sources=sources, candidate_ids=tuple(candidates))

    assert result.decision.decision_type == "REJECT"
    assert result.call_plan_parameters is None


def test_multiple_current_visible_read_candidates_show_options() -> None:
    result = _decide(candidate_ids=(INVENTORY_ID, PURCHASE_ORDER_ID))

    assert result.decision.decision_type == "SHOW_OPTIONS"
    assert [candidate.capability_id for candidate in result.decision.candidates] == [
        INVENTORY_ID,
        PURCHASE_ORDER_ID,
    ]
    assert result.call_plan_parameters is None


@pytest.mark.parametrize(
    "mutation",
    [
        "inactive",
        "restricted",
        "write",
        "approval",
        "missing-binding",
        "write-binding",
    ],
)
def test_non_current_or_non_execution_cards_fail_closed(mutation: str) -> None:
    capabilities = _thaw(BASE_SOURCES.capabilities)["capabilities"]
    bindings = _thaw(BASE_SOURCES.executor_bindings)["bindings"]
    inventory = next(
        capability
        for capability in capabilities
        if capability["capabilityId"] == INVENTORY_ID
    )
    if mutation == "inactive":
        inventory["status"] = "inactive"
    elif mutation == "restricted":
        inventory["governance"]["dataClassification"] = "restricted"
    elif mutation == "write":
        inventory["governance"]["sideEffect"] = "sap_write"
    elif mutation == "approval":
        inventory["governance"]["requiresApproval"] = True
    elif mutation == "missing-binding":
        bindings = [
            binding
            for binding in bindings
            if binding["bindingId"] != "sap.mm.inventory.md04-stock-req-list"
        ]
    else:
        binding = next(
            binding
            for binding in bindings
            if binding["bindingId"] == "sap.mm.inventory.md04-stock-req-list"
        )
        binding["constraints"]["sideEffect"] = "sap_write"
    result = _decide(
        sources=_sources(capabilities=capabilities, bindings=bindings),
        candidate_ids=(INVENTORY_ID,),
    )

    assert result.decision.decision_type == "REJECT"


def test_multi_read_goal_candidates_escalate_without_a_call_plan() -> None:
    result = _decide(
        candidate_ids=(INVENTORY_ID, PURCHASE_ORDER_ID),
        purpose="MULTI_GOAL",
    )

    assert result.decision.decision_type == "ESCALATE_TO_PLANNER"
    assert result.call_plan_parameters is None


def test_unknown_and_model_candidate_slots_are_rejected() -> None:
    frame = _resolution().next_state.active_frame
    assert frame is not None
    technical = SlotBinding(
        name="rfcName",
        value="BAPI_EVIL",
        candidates=("BAPI_EVIL",),
        state="RESOLVED",
        provenance="EXPLICIT",
        source_turn_id="turn-1",
        source_span=None,
        issues=(),
    )
    model_material = dataclasses.replace(
        frame.slots["material"], provenance="MODEL_CANDIDATE"
    )
    for slots in (
        {**frame.slots, "rfcName": technical},
        {**frame.slots, "material": model_material},
    ):
        adjusted = dataclasses.replace(frame, slots=slots)
        result = _decide(
            dataclasses.replace(
                _resolution(),
                next_state=ConversationReadState(adjusted, None, 1),
            ),
            candidate_ids=(INVENTORY_ID,),
        )
        assert result.decision.decision_type == "REJECT"


def test_conflicted_optional_slot_is_an_actionable_clarification_field() -> None:
    frame = _resolution().next_state.active_frame
    assert frame is not None
    conflicted = SlotBinding(
        name="unit",
        value=None,
        candidates=("EA", "KG"),
        state="CONFLICTED",
        provenance="EXPLICIT",
        source_turn_id="turn-1",
        source_span=None,
        issues=("conflict",),
    )
    adjusted = dataclasses.replace(
        frame,
        slots={**frame.slots, "unit": conflicted},
        status="CONFLICTED",
    )
    result = _decide(
        dataclasses.replace(_resolution(), next_state=ConversationReadState(adjusted, None, 1)),
        candidate_ids=(INVENTORY_ID,),
    )

    assert result.decision.decision_type == "CLARIFY"
    assert result.decision.missing_parameters == ["unit"]
