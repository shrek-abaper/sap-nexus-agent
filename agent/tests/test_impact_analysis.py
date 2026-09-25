"""Tests for Change Impact Analysis."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sap_nexus_agent.impact_analysis import (
    ImpactGraph,
    build_impact_graph,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def graph():
    return build_impact_graph(REPO_ROOT)


def test_graph_is_deterministic():
    first = build_impact_graph(REPO_ROOT)
    second = build_impact_graph(REPO_ROOT)

    assert first == second


def test_rule_change_affects_capability_and_fact(graph):
    report = graph.analyze(rule_id="sapnexus:rule.pr-quantity-is-supply-gap")

    assert "MM.PR.CreateDraft" in report.affected_capabilities
    assert "PurchaseRequisitionCreatedFact" in report.affected_fact_types


def test_semantic_type_change_finds_inputs(graph):
    report = graph.analyze(semantic_type="sapnexus:MaterialNumber")

    assert "MM.Inventory.GetAvailability" in report.affected_capabilities
    assert "MM.Material.GetInfo" in report.affected_capabilities


def test_transitive_propagation_through_fact_type(graph):
    # MaterialNumber -> Material.GetInfo -> MaterialInfoFact -> PR.CreateDraft
    report = graph.analyze(semantic_type="sapnexus:MaterialNumber")

    assert "MM.PR.CreateDraft" in report.affected_capabilities
    assert "MaterialInfoFact" in report.affected_fact_types


def test_type_change_excludes_unrelated_capabilities(graph):
    report = graph.analyze(semantic_type="sapnexus:MaterialNumber")

    assert "FI.AR.GetOpenItems" not in report.affected_capabilities
    assert "FI.AP.GetOpenItems" not in report.affected_capabilities


def test_affected_approvals_from_dict_records(graph):
    approvals = [
        {"approvalId": "a1", "capabilityId": "MM.PR.CreateDraft"},
        {"approvalId": "a2", "capabilityId": "FI.AR.GetOpenItems"},
    ]
    report = graph.analyze(
        rule_id="sapnexus:rule.pr-quantity-is-supply-gap",
        active_approvals=approvals,
    )

    assert report.affected_approvals == ["a1"]


def test_affected_approvals_accepts_objects(graph):
    approvals = [
        SimpleNamespace(approval_id="obj-1", capability_id="MM.PR.CreateDraft"),
    ]
    report = graph.analyze(
        rule_id="sapnexus:rule.pr-quantity-is-supply-gap",
        active_approvals=approvals,
    )

    assert report.affected_approvals == ["obj-1"]


def test_unknown_change_returns_empty(graph):
    report = graph.analyze(rule_id="sapnexus:rule.does-not-exist")

    assert report.affected_capabilities == []
    assert report.affected_fact_types == []
    assert report.affected_approvals == []


def test_report_is_pure_and_serializable(graph):
    report = graph.analyze(
        semantic_type="sapnexus:MaterialNumber",
        active_approvals=[{"approvalId": "x", "capabilityId": "MM.PR.CreateDraft"}],
    )
    serialized = report.as_dict()

    assert isinstance(serialized["affected_capabilities"], list)
    assert "x" in serialized["affected_approvals"]
