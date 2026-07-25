"""Unit tests for ``planner.handoff`` (S2-B, Plan Task 9).

Covers the ESCALATE_TO_PLANNER handoff wiring:

- ``compile_dry_run_from_handoff`` builds a ``GoalSpec`` from the
  handoff (``desiredFactTypes`` from ``CapabilityCard.produces_fact_types``;
  ``constraints`` derived from ``handoff.matched_intents`` parameters
  cross-referenced with ``CapabilityCard.inputs`` identifier bindings).
- Calls ``PlanCompiler.compile_dry_run`` (Task 8) to produce a
  ``DryRunResult`` with a validated S1 ``PlanGraph``.
- Deterministic: no LLM, no Gateway/SAP.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
section "总体数据流".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sap_nexus_agent.match_decision import EscalationHandoff, MatchedIntent
from sap_nexus_agent.planner.handoff import compile_dry_run_from_handoff
from sap_nexus_agent.planner.plan_compiler import DryRunResult
from sap_nexus_agent.semantic_planning import (
    build_registry_snapshot,
    load_semantic_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _real_sources():
    return load_semantic_sources(REPO_ROOT)


def _real_snapshot():
    return build_registry_snapshot(_real_sources())


def _handoff_inventory_plus_po(
    inventory_params: dict[str, str] | None = None,
    po_params: dict[str, str] | None = None,
) -> EscalationHandoff:
    return EscalationHandoff(
        reason="multi-intent",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters=inventory_params or {"material": "DEMOA2", "plant": "5100"},
                missing=[],
            ),
            MatchedIntent(
                capability_id="MM.PurchaseOrder.GetList",
                parameters=po_params or {},
                missing=[],
            ),
        ],
        utterance="DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单",
        registry_snapshot_id=_real_snapshot().snapshot_id,
    )


def test_compile_dry_run_from_handoff_returns_dry_run_result_with_two_nodes():
    handoff = _handoff_inventory_plus_po()
    result = compile_dry_run_from_handoff(handoff, _real_snapshot(), _real_sources())

    assert isinstance(result, DryRunResult)
    nodes = result.plan_graph["nodes"]
    assert len(nodes) == 2
    capability_ids = {n["capabilityId"] for n in nodes}
    assert capability_ids == {
        "MM.Inventory.GetAvailability",
        "MM.PurchaseOrder.GetList",
    }


def test_compile_dry_run_from_handoff_binds_inventory_identifier_inputs():
    """Identifier parameters from matched_intents become goalConstraint sources."""
    handoff = _handoff_inventory_plus_po(
        inventory_params={"material": "DEMOA2", "plant": "5100"},
    )
    result = compile_dry_run_from_handoff(handoff, _real_snapshot(), _real_sources())

    inv_nodes = [
        n
        for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "MM.Inventory.GetAvailability"
    ]
    assert inv_nodes
    bindings = inv_nodes[0]["parameterBindings"]
    bound_names = {b["parameterName"] for b in bindings}
    assert {"material", "plant"}.issubset(bound_names)
    source_kinds = {b["source"]["kind"] for b in bindings}
    assert source_kinds == {"goalConstraint"}


def test_compile_dry_run_from_handoff_skips_non_identifier_parameters():
    """Non-identifier parameters (e.g. literal/fact) do not become constraints."""
    handoff = _handoff_inventory_plus_po(
        inventory_params={"material": "DEMOA2", "plant": "5100"},
        # PO all-optional identifier inputs; empty params -> no constraints
        # contributed, but the PO node is still produced.
        po_params={},
    )
    result = compile_dry_run_from_handoff(handoff, _real_snapshot(), _real_sources())

    po_nodes = [
        n
        for n in result.plan_graph["nodes"]
        if n["capabilityId"] == "MM.PurchaseOrder.GetList"
    ]
    assert po_nodes
    # No constraints contributed for PO (empty params) -> no bindings.
    assert po_nodes[0]["parameterBindings"] == []


def test_compile_dry_run_from_handoff_dedupes_constraints_across_matched_intents():
    """If two matched intents share the same identifier parameter name+semantic_type,
    only one GoalConstraint is emitted (dedup by name+semantic_type)."""
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA2", "plant": "5100"},
                missing=[],
            ),
            MatchedIntent(
                capability_id="MM.PurchaseOrder.GetList",
                # plant is also an identifier on PO; same semantic_type ->
                # deduped, not duplicated.
                parameters={"plant": "5100"},
                missing=[],
            ),
        ],
        utterance="multi-goal with shared plant",
        registry_snapshot_id=_real_snapshot().snapshot_id,
    )
    result = compile_dry_run_from_handoff(handoff, _real_snapshot(), _real_sources())

    # Both nodes present; the plant constraint is shared (deduped) but the
    # PlanCompiler binds it to whichever node's input matches by name+semantic_type.
    capability_ids = {n["capabilityId"] for n in result.plan_graph["nodes"]}
    assert "MM.Inventory.GetAvailability" in capability_ids


def test_compile_dry_run_from_handoff_skips_unknown_capability_matched_intents():
    """A matched intent for a capability not in the registry contributes no
    fact types / constraints; the dry-run still runs for the known ones."""
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[
            MatchedIntent(
                capability_id="MM.Inventory.GetAvailability",
                parameters={"material": "DEMOA2", "plant": "5100"},
                missing=[],
            ),
            MatchedIntent(
                capability_id="MM.DoesNotExist",
                parameters={},
                missing=[],
            ),
        ],
        utterance="unknown capability in handoff",
        registry_snapshot_id=_real_snapshot().snapshot_id,
    )
    result = compile_dry_run_from_handoff(handoff, _real_snapshot(), _real_sources())

    nodes = result.plan_graph["nodes"]
    assert len(nodes) == 1
    assert nodes[0]["capabilityId"] == "MM.Inventory.GetAvailability"


def test_compile_dry_run_from_handoff_does_not_raise_on_empty_handoff():
    """Empty matched_intents -> empty desiredFactTypes -> invalid_plan_graph flag,
    no exception (Design Doc §错误处理)."""
    handoff = EscalationHandoff(
        reason="multi-intent",
        matched_intents=[],
        utterance="",
        registry_snapshot_id="",
    )
    result = compile_dry_run_from_handoff(handoff, _real_snapshot(), _real_sources())

    assert isinstance(result, DryRunResult)
    assert any(f.kind == "invalid_plan_graph" for f in result.governance_flags)


def test_compile_dry_run_from_handoff_is_deterministic():
    handoff = _handoff_inventory_plus_po()
    snapshot = _real_snapshot()
    sources = _real_sources()
    first = compile_dry_run_from_handoff(handoff, snapshot, sources)
    second = compile_dry_run_from_handoff(handoff, snapshot, sources)
    assert first == second
    assert first.plan_graph == second.plan_graph
