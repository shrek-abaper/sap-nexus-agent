"""Contract dataclass and bounds tests for ontology_planning (C2)."""

from __future__ import annotations

import dataclasses

import pytest

from sap_nexus_agent.ontology_planning.bounds import BOUNDS
from sap_nexus_agent.ontology_planning.contracts import (
    AnalysisNodeDraft,
    ObjectSelector,
    RequestedConclusion,
    RequestedFact,
    SemanticGoalDraft,
    TypedConstraint,
)


def test_bounds_constants():
    assert BOUNDS.max_read_nodes == 6
    assert BOUNDS.max_analysis_nodes == 6
    assert BOUNDS.max_depth == 4
    assert BOUNDS.max_model_turns == 2
    assert BOUNDS.overall_timeout_seconds == 90
    assert BOUNDS.max_rows == 5000
    assert BOUNDS.max_response_bytes == 2 * 1024 * 1024


def test_minimal_draft_round_trip():
    draft = SemanticGoalDraft(
        schema_version=1,
        requested_facts=(
            RequestedFact(
                fact_type_id="sapnexus:InventoryAvailabilityFact",
                fields=("availableQuantity",),
                selectors=(
                    ObjectSelector("sapnexus:Material", "material", "DEMOA2"),
                ),
            ),
        ),
        constraints=(
            TypedConstraint(
                "plant", "sapnexus:Plant", "1000", source="explicitUser"
            ),
        ),
        analysis_nodes=(),
        requested_conclusions=(
            RequestedConclusion("c1", "current stock", "fact with unit"),
        ),
        assumptions=(),
    )
    document = draft.to_dict()
    assert document == {
        "schemaVersion": 1,
        "requestedFacts": [
            {
                "factTypeId": "sapnexus:InventoryAvailabilityFact",
                "fields": ["availableQuantity"],
                "objectSelectors": [
                    {"objectTypeId": "sapnexus:Material", "key": "material",
                     "value": "DEMOA2"}
                ],
            }
        ],
        "constraints": [
            {"name": "plant", "semanticType": "sapnexus:Plant",
             "value": "1000", "source": "explicitUser"}
        ],
        "analysisNodes": [],
        "requestedConclusions": [
            {"id": "c1", "statement": "current stock",
             "evidenceRequirement": "fact with unit"}
        ],
        "assumptions": [],
    }
    assert SemanticGoalDraft.from_dict(document) == draft


def test_constraint_source_is_closed():
    with pytest.raises(ValueError):
        TypedConstraint("plant", "sapnexus:Plant", "1000", source="model")
    TypedConstraint("plant", "sapnexus:Plant", "1000", source="confirmedContext")


def test_analysis_node_draft_frozen():
    node = AnalysisNodeDraft("a1", "select_fields", (), {}, ())
    with pytest.raises(dataclasses.FrozenInstanceError):
        node.operator_id = "group_sum"  # type: ignore[misc]
