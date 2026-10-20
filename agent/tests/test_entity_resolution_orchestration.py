"""Phase B end-to-end tests: description -> candidates -> selection -> resume.

Runs the real orchestrator with ENTITY_RESOLUTION_MODE=on against a
FakeGateway that serves the governed MD.*.Search responses and records every
inventory execution. No real PG here: the governed search path's PG behavior
is pinned by agent/tests/test_master_data_pg.py and the Java adapter tests;
these tests pin the orchestration, pending, and selection semantics.
"""

from __future__ import annotations

import pytest

from sap_nexus_agent.conversation_context import ConversationContext
from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.governed_context import PLACEHOLDER_PRINCIPAL, TrustedPrincipal
from sap_nexus_agent.orchestrator import run_query
from sap_nexus_agent.read_context import ConversationReadState

INVENTORY = "MM.Inventory.GetAvailability"
MD_SEARCH = "MD.Material.Search"


def _md_candidates(*codes: tuple[str, str, str]) -> list[dict]:
    """(code, display, size) tuples -> governed response candidate maps."""
    return [
        {
            "sourceSystem": "S4H",
            "client": "100",
            "objectType": "sapnexus:Material",
            "canonicalCode": code,
            "displayName": display,
            "distinguishing": {"sizeDimension": size, "materialGroup": "SEAL"},
            "matchKind": "substring",
            "status": "active",
            "orgScopes": [{"field": "plant", "value": "1000"}],
        }
        for code, display, size in codes
    ]


class FakeGateway:
    """Serves MD.*.Search from a script; executes inventory on demand."""

    def __init__(self, md_results: dict[str, list[dict]] | None = None):
        self.md_results = md_results or {}
        self.execute_calls: list[tuple[str, dict]] = []
        self.validate_calls: list[tuple[str, dict]] = []

    # -- gateway protocol -----------------------------------------------------
    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, parameters))
        return ValidationResult(
            trace_id="gw-validate", capability_id=capability_id,
            success=True, error_type="NONE", messages=[],
        )

    def execute(self, capability_id, parameters, approval_id=None):
        self.execute_calls.append((capability_id, dict(parameters)))
        if capability_id == MD_SEARCH:
            query = str(parameters.get("query") or "")
            entity_key = str(parameters.get("entityKey") or "")
            candidates = self.md_results.get("__all__", [])
            if entity_key:
                candidates = [
                    c for c in candidates
                    if c["canonicalCode"].upper() == entity_key.upper()
                ]
            elif query:
                candidates = [
                    c for c in candidates
                    if query in c["displayName"] or query in str(c["distinguishing"].values())
                ]
            return ExecutionResult(
                trace_id="gw-md", capability_id=capability_id,
                success=True, executor={"type": "PG_MASTERDATA_READ", "rfcName": None},
                return_messages=[],
                data={
                    "candidates": candidates,
                    "objectType": "sapnexus:Material",
                    "snapshotId": "snap-test-1",
                    "resultCompleteness": "complete-result-set",
                    "sourceExtractedAt": "2026-10-01T00:00:00Z",
                },
                duration_ms=5, error_type="NONE",
            )
        if capability_id == INVENTORY:
            return ExecutionResult(
                trace_id="gw-inv", capability_id=capability_id,
                success=True,
                executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_AVAILABILITY"},
                return_messages=[],
                data={
                    "material": parameters.get("material"),
                    "plant": parameters.get("plant"),
                    "availableQuantity": 12, "unit": "EA",
                },
                duration_ms=10, error_type="NONE",
            )
        raise AssertionError(f"unexpected gateway execute: {capability_id}")


SEALS = _md_candidates(
    ("DEMOA1", "蓝色耐高温密封圈 Ø20", "20mm"),
    ("DEMOA2", "蓝色耐高温密封圈 Ø25", "25mm"),
)


@pytest.fixture()
def gateway():
    return FakeGateway({"__all__": SEALS})


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "on")


def _turn(text, gateway, context=None, principal=PLACEHOLDER_PRINCIPAL):
    if context is None:
        context = ConversationContext(
            None, None, read_state=ConversationReadState(None, None, 0),
        )
    return run_query(
        text, gateway, context=context, principal=principal,
    )


def _inventory_calls(gateway):
    return [params for cap, params in gateway.execute_calls if cap == INVENTORY]


def test_description_turn_offers_candidates_without_executing(gateway):
    outcome = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)

    assert outcome.status == "clarification"
    assert outcome.entity_choice is not None
    codes = [c["canonicalCode"] for c in outcome.entity_choice["candidates"]]
    assert codes == ["DEMOA1", "DEMOA2"]
    assert "快照提取时间" in (outcome.response_text or "")
    # case 26: no downstream business read before entity confirmation
    assert _inventory_calls(gateway) == []
    pending = outcome.read_state.pending_interaction
    assert pending is not None and pending.kind == "ENTITY_CHOICE"
    assert pending.entity_choice.target_capability_id == INVENTORY
    assert pending.entity_choice.target_slot == "material"


def test_ordinal_selection_binds_original_order_and_resumes(gateway):
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    second = _turn("第二个", gateway, context=first.updated_context)

    calls = _inventory_calls(gateway)
    assert len(calls) == 1
    # case 13: "第二个" binds the ORIGINAL display order; case 21: plant kept
    assert calls[0]["material"] == "DEMOA2"
    assert calls[0]["plant"] == "1000"
    assert second.read_state.pending_interaction is None
    assert second.read_state.active_frame.slots["material"].provenance == "CONFIRMED"


def test_attribute_selection_unique_match(gateway):
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    second = _turn("20mm 的那个", gateway, context=first.updated_context)

    calls = _inventory_calls(gateway)
    assert len(calls) == 1 and calls[0]["material"] == "DEMOA1"


def test_refusal_clears_pending(gateway):
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    second = _turn("都不是", gateway, context=first.updated_context)

    assert second.status == "clarification"
    assert second.read_state.pending_interaction is None
    assert _inventory_calls(gateway) == []
    # case 17: a fresh description after refusal must not be swallowed
    third = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway, context=second.updated_context)
    assert third.entity_choice is not None


def test_new_description_replaces_candidate_set(gateway):
    gateway.md_results["__all__"] = SEALS + _md_candidates(
        ("SEAL-HT/B", "高温垫片 1.5mm", "1.5mm"),
    )
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    second = _turn("垫片", gateway, context=first.updated_context)

    assert second.entity_choice is not None
    new_set_id = second.entity_choice["candidateSetId"]
    assert [c["canonicalCode"] for c in second.entity_choice["candidates"]] == ["SEAL-HT/B"]
    # case 80: the old handle cannot select anymore
    assert new_set_id != first.entity_choice["candidateSetId"]
    third = _turn("第一个", gateway, context=second.updated_context)
    calls = _inventory_calls(gateway)
    assert len(calls) == 1 and calls[0]["material"] == "SEAL-HT/B"


def test_out_of_range_index_keeps_pending(gateway):
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    second = _turn("第 9 个", gateway, context=first.updated_context)

    assert second.status == "clarification"
    assert "不在候选范围" in (second.response_text or "")
    assert second.read_state.pending_interaction is not None
    assert _inventory_calls(gateway) == []


def test_cross_principal_handle_rejected(gateway):
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    other = TrustedPrincipal(
        principal_id="other-user", role="operator", data_scope={"tenantId": "default"},
    )
    second = _turn("第二个", gateway, context=first.updated_context, principal=other)

    assert second.status == "clarification"
    assert "不属于当前身份" in (second.response_text or "")
    assert _inventory_calls(gateway) == []


def test_snapshot_drift_invalidates_pending(gateway, monkeypatch):
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    # Forge a context whose pending was issued under another registry snapshot.
    pending = first.read_state.pending_interaction
    forged = pending.entity_choice.__class__.from_dict(
        {**pending.entity_choice.to_dict(), "registrySnapshotId": "sha256:other"}
    )
    drifted_pending = type(pending).entity_choice_pending(
        frame_id=pending.frame_id, choice_set=forged,
        state_version=pending.state_version,
        registry_snapshot_id=pending.registry_snapshot_id,
        expires_at=pending.expires_at,
    )
    drifted_state = type(first.read_state)(
        active_frame=first.read_state.active_frame,
        pending_interaction=drifted_pending,
        state_version=first.read_state.state_version,
        recent_frames=first.read_state.recent_frames,
    )
    context = first.updated_context
    context = type(context)(
        **{**context.__dict__, "read_state": drifted_state}
    )
    second = _turn("第二个", gateway, context=context)

    assert second.status == "clarification"
    assert "配置已更新" in (second.response_text or "")
    assert _inventory_calls(gateway) == []


def test_model_fabricated_code_gains_no_authority(gateway):
    # The utterance asserts a code; only the governed search may confirm it.
    outcome = _turn("物料编码 FAKE99 在 1000 的库存", gateway)

    assert _inventory_calls(gateway) == []
    assert outcome.status == "clarification"
    # FAKE99 never reaches the inventory capability
    for params in _inventory_calls(gateway):
        assert params.get("material") != "FAKE99"


def test_feature_flag_off_keeps_legacy_path(gateway, monkeypatch):
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "off")
    outcome = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)

    assert outcome.status == "clarification"
    assert outcome.entity_choice is None
    # case 28: no master-data search happens when the flag is off
    assert all(cap != MD_SEARCH for cap, _ in gateway.execute_calls)


def test_single_fuzzy_candidate_still_requires_confirmation(gateway):
    # case 15: even one fuzzy hit is not auto-bound
    gateway.md_results["__all__"] = _md_candidates(
        ("SEAL-HT/B", "高温垫片 1.5mm", "1.5mm"),
    )
    outcome = _turn("查一下高温垫片在 1000 工厂的库存", gateway)

    assert outcome.status == "clarification"
    assert outcome.entity_choice is not None
    assert len(outcome.entity_choice["candidates"]) == 1
    assert _inventory_calls(gateway) == []
    # confirming binds it
    second = _turn("第一个", gateway, context=outcome.updated_context)
    calls = _inventory_calls(gateway)
    assert len(calls) == 1 and calls[0]["material"] == "SEAL-HT/B"


def test_attribute_selection_still_ambiguous_keeps_asking(gateway):
    # case 14: an attribute phrase matching several candidates asks again
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    second = _turn("密封圈的那家", gateway, context=first.updated_context)

    assert second.status == "clarification"
    assert "仍有多个匹配" in (second.response_text or "")
    assert second.read_state.pending_interaction is not None
    assert _inventory_calls(gateway) == []
    # a following ordinal still binds against the original set
    third = _turn("第二个", gateway, context=second.updated_context)
    calls = _inventory_calls(gateway)
    assert len(calls) == 1 and calls[0]["material"] == "DEMOA2"


def test_retry_binds_same_object_and_durable_layer_dedupes(gateway):
    # case 20 (retry half): repeating the SAME context+answer is a retry; it
    # re-derives the SAME object, and the existing idempotency/lease protocol
    # (frontend durable store) dedupes the continuation — this layer must at
    # least never bind a different object.
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    _turn("第二个", gateway, context=first.updated_context)
    replay = _turn("第二个", gateway, context=first.updated_context)
    materials = [c["material"] for c in _inventory_calls(gateway)]
    assert set(materials) == {"DEMOA2"}
    assert replay.read_state.active_frame.slots["material"].value == "DEMOA2"


def test_stale_state_version_pending_is_rejected(gateway):
    # case 20 (stale half): a pending whose state_version does not match the
    # presented state is rejected by the reducer and never executes.
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    stale_state = type(first.read_state)(
        active_frame=first.read_state.active_frame,
        pending_interaction=first.read_state.pending_interaction,
        state_version=first.read_state.state_version + 7,
        recent_frames=first.read_state.recent_frames,
    )
    context = type(first.updated_context)(
        **{**first.updated_context.__dict__, "read_state": stale_state}
    )
    second = _turn("第二个", gateway, context=context)
    assert _inventory_calls(gateway) == []


def test_expired_candidate_set_is_rejected(gateway, monkeypatch):
    # case 18: an expired pending never grants authority
    first = _turn("查一下蓝色耐高温密封圈在 1000 工厂的库存", gateway)
    pending = first.read_state.pending_interaction
    expired_choice = pending.entity_choice.__class__.from_dict(
        {**pending.entity_choice.to_dict(), "expiresAt": "2020-01-01T00:00:00Z"}
    )
    expired_pending = type(pending).entity_choice_pending(
        frame_id=pending.frame_id, choice_set=expired_choice,
        state_version=pending.state_version,
        registry_snapshot_id=pending.registry_snapshot_id,
        expires_at="2020-01-01T00:00:00Z",
    )
    expired_state = type(first.read_state)(
        active_frame=first.read_state.active_frame,
        pending_interaction=expired_pending,
        state_version=first.read_state.state_version,
        recent_frames=first.read_state.recent_frames,
    )
    context = type(first.updated_context)(
        **{**first.updated_context.__dict__, "read_state": expired_state}
    )
    second = _turn("第二个", gateway, context=context)
    assert _inventory_calls(gateway) == []
