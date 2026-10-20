"""Structural and business validation tests for SemanticRelease assets."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sap_nexus_agent.semantic_release.assets import (
    SEMANTIC_SOURCE_MANIFEST,
    load_release_assets,
)
from sap_nexus_agent.semantic_release.validation import (
    assess_business_validity,
    validate_structure,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _digest(document: dict) -> str:
    from sap_nexus_agent.semantic_planning.snapshot import (
        canonical_json_bytes,
    )
    import hashlib

    return "sha256:" + hashlib.sha256(canonical_json_bytes(document)).hexdigest()


@pytest.fixture
def real_assets():
    return load_release_assets(REPO_ROOT)


def _source(path: str, document: dict, role: str = "semantic") -> dict:
    return {
        "path": path,
        "documentVersion": int(document.get("version", 1)),
        "digest": _digest(document),
        "role": role,
    }


def _valid_package_dict(assets: dict[str, dict], legacy_snapshot_id: str = "sha256:" + "0" * 64):
    from sap_nexus_agent.semantic_release.validation import (
        compute_semantic_snapshot_id,
    )

    versions = assets["ontology/analysis-versions.yaml"]
    sources = [
        _source(path, document) for path, document in sorted(assets.items())
    ]
    return {
        "schemaVersion": 1,
        "registrySnapshotId": legacy_snapshot_id,
        "semanticSnapshotId": compute_semantic_snapshot_id(
            sources, versions["compilerVersion"], versions["operatorImplementations"]
        ),
        "compilerVersion": versions["compilerVersion"],
        "operatorImplementationVersion": dict(versions["operatorImplementations"]),
        "sources": sources,
        "businessValidity": {"applicability": []},
    }


def test_manifest_lists_nine_semantic_sources():
    semantic = {path for path, role in SEMANTIC_SOURCE_MANIFEST if role == "semantic"}
    assert semantic == {
        "ontology/analysis-fact-fields.yaml",
        "ontology/analysis-operators.yaml",
        "ontology/analysis-versions.yaml",
        "ontology/definition-applicability.yaml",
        "ontology/object-types.yaml",
        "ontology/definitions.yaml",
        "ontology/object-links.yaml",
        "ontology/business-rules.yaml",
        "ontology/entity-resolution.yaml",
    }


def test_real_repo_package_is_structurally_valid(real_assets):
    report = validate_structure(
        _valid_package_dict(real_assets), real_assets, registry_snapshot_id="sha256:" + "0" * 64
    )
    assert report.valid, [str(i) for i in report.issues]


def test_unknown_field_ref_fails(real_assets):
    assets = {k: v for k, v in real_assets.items()}
    import copy

    broken = copy.deepcopy(assets["ontology/analysis-fact-fields.yaml"])
    broken["allowlist"][0]["fields"].append(
        {"name": "notAField", "semanticType": "sapnexus:AvailableQuantity"}
    )
    assets["ontology/analysis-fact-fields.yaml"] = broken
    pkg = _valid_package_dict(assets)
    report = validate_structure(pkg, assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert not report.valid
    assert any(i.code == "SR_UNKNOWN_FIELD_REF" for i in report.issues)


def test_unknown_fact_type_ref_fails(real_assets):
    import copy

    assets = {k: v for k, v in real_assets.items()}
    broken = copy.deepcopy(assets["ontology/analysis-fact-fields.yaml"])
    broken["allowlist"][0]["factTypeId"] = "sapnexus:DoesNotExistFact"
    assets["ontology/analysis-fact-fields.yaml"] = broken
    pkg = _valid_package_dict(assets)
    report = validate_structure(pkg, assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert any(i.code == "SR_UNKNOWN_FACT_TYPE" for i in report.issues)


def test_unknown_semantic_type_ref_fails(real_assets):
    import copy

    assets = {k: v for k, v in real_assets.items()}
    broken = copy.deepcopy(assets["ontology/object-types.yaml"])
    broken["objectTypes"][0]["semanticType"] = "sapnexus:NotAType"
    assets["ontology/object-types.yaml"] = broken
    pkg = _valid_package_dict(assets)
    report = validate_structure(pkg, assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert any(i.code == "SR_UNKNOWN_SEMANTIC_TYPE" for i in report.issues)


def test_unknown_operator_ref_fails(real_assets):
    import copy

    assets = {k: v for k, v in real_assets.items()}
    broken = copy.deepcopy(assets["ontology/analysis-operators.yaml"])
    broken["operators"][0]["operatorId"] = "unknown_op"
    assets["ontology/analysis-operators.yaml"] = broken
    pkg = _valid_package_dict(assets)
    report = validate_structure(pkg, assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert any(
        i.code in {"SR_UNKNOWN_OPERATOR", "SR_OPERATOR_NOT_IN_CLOSED_SET"}
        for i in report.issues
    )


def test_operator_catalog_not_closed_set_fails(real_assets):
    import copy

    assets = {k: v for k, v in real_assets.items()}
    versions = copy.deepcopy(assets["ontology/analysis-versions.yaml"])
    versions["operatorImplementations"]["fifth_op"] = "0.1.0"
    assets["ontology/analysis-versions.yaml"] = versions
    pkg = _valid_package_dict(assets)
    report = validate_structure(pkg, assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert any(i.code == "SR_OPERATOR_NOT_IN_CLOSED_SET" for i in report.issues)


def test_unknown_definition_ref_fails(real_assets):
    import copy

    assets = {k: v for k, v in real_assets.items()}
    broken = copy.deepcopy(assets["ontology/definition-applicability.yaml"])
    broken["applicability"].append(
        {
            "definitionId": "sapnexus:def.does-not-exist",
            "status": "grounded",
            "applicableScopes": ["MM"],
        }
    )
    assets["ontology/definition-applicability.yaml"] = broken
    pkg = _valid_package_dict(assets)
    report = validate_structure(pkg, assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert any(i.code == "SR_UNKNOWN_DEFINITION_REF" for i in report.issues)


def test_digest_mismatch_fails(real_assets):
    pkg = _valid_package_dict(real_assets)
    pkg["sources"][0]["digest"] = "sha256:" + "9" * 64
    report = validate_structure(pkg, real_assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert any(i.code == "SR_DIGEST_MISMATCH" for i in report.issues)


def test_snapshot_id_mismatch_fails(real_assets):
    pkg = _valid_package_dict(
        real_assets, legacy_snapshot_id="sha256:" + "0" * 64
    )
    report = validate_structure(
        pkg, real_assets, registry_snapshot_id="sha256:" + "1" * 64
    )
    assert any(i.code == "SR_SNAPSHOT_ID_MISMATCH" for i in report.issues)


def test_duplicate_source_fails(real_assets):
    pkg = _valid_package_dict(real_assets)
    pkg["sources"].append(dict(pkg["sources"][0]))
    report = validate_structure(pkg, real_assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert any(i.code == "SR_DUPLICATE_SOURCE" for i in report.issues)


def test_manifest_violation_fails(real_assets):
    pkg = _valid_package_dict(real_assets)
    pkg["sources"] = [s for s in pkg["sources"] if s["role"] != "semantic"][:1]
    report = validate_structure(pkg, real_assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert any(i.code == "SR_MANIFEST_VIOLATION" for i in report.issues)


def test_schema_invalid_fails(real_assets):
    pkg = _valid_package_dict(real_assets)
    del pkg["semanticSnapshotId"]
    report = validate_structure(pkg, real_assets, registry_snapshot_id="sha256:" + "0" * 64)
    assert any(i.code == "SR_SCHEMA_INVALID" for i in report.issues)


def test_business_validity_empty(real_assets):
    report = assess_business_validity(real_assets)
    assert report.entries == ()


def test_business_validity_grounded_and_proposed(real_assets):
    import copy

    assets = {k: v for k, v in real_assets.items()}
    applicability = copy.deepcopy(assets["ontology/definition-applicability.yaml"])
    applicability["applicability"] = [
        {
            "definitionId": "sapnexus:def.available-for-commitment",
            "status": "grounded",
            "applicableScopes": ["MM"],
        },
        {
            "definitionId": "sapnexus:def.overdue",
            "status": "proposed",
            "applicableScopes": ["FI"],
        },
    ]
    assets["ontology/definition-applicability.yaml"] = applicability
    report = assess_business_validity(assets)
    by_id = {e.definition_id: e for e in report.entries}
    assert by_id["sapnexus:def.available-for-commitment"].state == "grounded"
    assert by_id["sapnexus:def.overdue"].state == "not_grounded"


def test_tampered_legacy_digest_fails(real_assets):
    from sap_nexus_agent.semantic_release.builder import build_semantic_release

    document = build_semantic_release(REPO_ROOT).to_dict()
    legacy_row = next(s for s in document["sources"] if s["role"] == "legacy")
    legacy_row["digest"] = "sha256:" + "9" * 64
    report = validate_structure(
        document,
        real_assets,
        registry_snapshot_id=document["registrySnapshotId"],
        repo_root=REPO_ROOT,
    )
    assert any(i.code == "SR_DIGEST_MISMATCH" for i in report.issues)
