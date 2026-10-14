"""Tests for SemanticRelease frozen package and validation contracts."""

from __future__ import annotations

import dataclasses

import pytest

from sap_nexus_agent.semantic_release.contracts import (
    BusinessValidityEntry,
    BusinessValidityReport,
    ReleaseSource,
    SemanticReleaseIssue,
    SemanticReleasePackage,
    StructuralValidationReport,
    STRUCTURAL_ISSUE_CODES,
)


def test_release_source_and_package_to_dict_camelcase():
    pkg = SemanticReleasePackage(
        schema_version=1,
        registry_snapshot_id="sha256:aaa",
        semantic_snapshot_id="sha256:bbb",
        compiler_version="0.1.0",
        operator_implementation_version={"select_fields": "0.1.0"},
        sources=(
            ReleaseSource(
                path="ontology/analysis-versions.yaml",
                document_version=1,
                digest="sha256:c",
                role="semantic",
            ),
        ),
        business_validity={"applicability": []},
    )
    assert pkg.to_dict() == {
        "schemaVersion": 1,
        "registrySnapshotId": "sha256:aaa",
        "semanticSnapshotId": "sha256:bbb",
        "compilerVersion": "0.1.0",
        "operatorImplementationVersion": {"select_fields": "0.1.0"},
        "sources": [
            {
                "path": "ontology/analysis-versions.yaml",
                "documentVersion": 1,
                "digest": "sha256:c",
                "role": "semantic",
            }
        ],
        "businessValidity": {"applicability": []},
    }


def test_issue_codes_are_closed():
    expected = {
        "SR_SCHEMA_INVALID",
        "SR_UNKNOWN_FIELD_REF",
        "SR_UNKNOWN_FACT_TYPE",
        "SR_UNKNOWN_SEMANTIC_TYPE",
        "SR_UNKNOWN_OPERATOR",
        "SR_OPERATOR_NOT_IN_CLOSED_SET",
        "SR_UNKNOWN_DEFINITION_REF",
        "SR_DIGEST_MISMATCH",
        "SR_SNAPSHOT_ID_MISMATCH",
        "SR_DUPLICATE_SOURCE",
        "SR_MANIFEST_VIOLATION",
    }
    assert set(STRUCTURAL_ISSUE_CODES) == expected


def test_reports_and_package_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        StructuralValidationReport(True, ()).valid = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        BusinessValidityReport(
            (BusinessValidityEntry("sapnexus:def.x", "grounded", "grounded"),)
        ).entries = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        SemanticReleaseIssue("a", "SR_SCHEMA_INVALID", "m").code = "x"  # type: ignore[misc]
