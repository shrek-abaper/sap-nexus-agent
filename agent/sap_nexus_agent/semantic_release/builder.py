"""Deterministic assembly of SemanticRelease v1 packages."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.snapshot import canonical_json_bytes
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

from .assets import SEMANTIC_SOURCE_MANIFEST, load_release_assets
from .contracts import ReleaseSource, SemanticReleasePackage
from .validation import (
    assess_business_validity,
    compute_semantic_snapshot_id,
    validate_structure,
)


def _sha256(document: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def build_semantic_release(repo_root: Path) -> SemanticReleasePackage:
    """Build one validated package from the working tree at repo_root."""
    sources = load_semantic_sources(repo_root)
    contracts = build_semantic_contracts(sources)
    if not contracts.report.valid or contracts.snapshot is None:
        problems = "; ".join(
            f"{issue.path}:{issue.code}:{issue.message}"
            for issue in contracts.report.issues
        )
        raise RuntimeError(f"legacy registry snapshot is invalid: {problems}")

    legacy_rows = [
        ReleaseSource(
            path=entry.path,
            document_version=entry.document_version,
            digest=entry.digest,
            role="legacy",
        )
        for entry in contracts.snapshot.sources
    ]

    assets = load_release_assets(repo_root)
    semantic_rows = [
        ReleaseSource(
            path=path,
            document_version=int(document["version"]),
            digest=_sha256(document),
            role="semantic",
        )
        for path, _role in SEMANTIC_SOURCE_MANIFEST
        for document in [assets[path]]
    ]

    versions = assets["ontology/analysis-versions.yaml"]
    all_rows = tuple(
        sorted((*legacy_rows, *semantic_rows), key=lambda row: row.path)
    )
    semantic_snapshot_id = compute_semantic_snapshot_id(
        [row.to_dict() for row in semantic_rows],
        versions["compilerVersion"],
        dict(versions["operatorImplementations"]),
    )

    business_report = assess_business_validity(assets)
    applicability = [
        {
            "definitionId": entry.definition_id,
            "declaredStatus": entry.declared_status,
            "state": entry.state,
        }
        for entry in business_report.entries
    ]

    package = SemanticReleasePackage(
        schema_version=1,
        registry_snapshot_id=contracts.snapshot.snapshot_id,
        semantic_snapshot_id=semantic_snapshot_id,
        compiler_version=versions["compilerVersion"],
        operator_implementation_version=dict(
            versions["operatorImplementations"]
        ),
        sources=tuple(all_rows),
        business_validity={"applicability": applicability},
    )

    report = validate_structure(
        package.to_dict(),
        assets,
        registry_snapshot_id=contracts.snapshot.snapshot_id,
        repo_root=repo_root,
    )
    if not report.valid:
        problems = "; ".join(
            f"{issue.path}:{issue.code}:{issue.message}"
            for issue in report.issues
        )
        raise RuntimeError(f"semantic release failed validation: {problems}")

    return package
