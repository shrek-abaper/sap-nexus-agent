"""Structural validation and business-validity assessment for releases."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema

from sap_nexus_agent.semantic_planning.loader import (
    load_semantic_sources,
    load_yaml_mapping,
)
from sap_nexus_agent.semantic_planning.snapshot import canonical_json_bytes

from .assets import (
    ASSET_SCHEMAS,
    CLOSED_OPERATOR_IDS,
    LEGACY_SOURCE_PATHS,
    SEMANTIC_SOURCE_MANIFEST,
)
from .contracts import (
    BusinessValidityEntry,
    BusinessValidityReport,
    SemanticReleaseIssue,
    StructuralValidationReport,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

SEMANTIC_PATHS = frozenset(path for path, _role in SEMANTIC_SOURCE_MANIFEST)
_LEGACY_PATHS = frozenset(LEGACY_SOURCE_PATHS)


def _sha256(document: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def _load_schema(repo_root: Path, name: str) -> dict[str, Any]:
    return json.loads((repo_root / "schemas" / name).read_text(encoding="utf-8"))


def compute_semantic_snapshot_id(
    sources: list[dict[str, Any]],
    compiler_version: str,
    operator_versions: Mapping[str, str],
) -> str:
    """Deterministic aggregate content id over source rows and version markers."""
    payload = {
        "sources": sorted(
            (
                {
                    "path": row["path"],
                    "documentVersion": row["documentVersion"],
                    "digest": row["digest"],
                    "role": row["role"],
                }
                for row in sources
            ),
            key=lambda row: row["path"],
        ),
        "compilerVersion": compiler_version,
        "operatorImplementationVersion": dict(
            sorted(operator_versions.items())
        ),
    }
    return _sha256(payload)


def _collect_vocabulary(legacy: dict[str, dict[str, Any]]) -> frozenset[str]:
    types: set[str] = set()
    capabilities = legacy.get("registry/capabilities.yaml", {})
    for capability in capabilities.get("capabilities", []):
        for field_name in ("inputs", "outputs"):
            for field in capability.get(field_name, []):
                semantic_type = field.get("semanticType")
                if semantic_type:
                    types.add(semantic_type)
    fact_types = legacy.get("ontology/fact-types.yaml", {})
    for fact_type in fact_types.get("factTypes", []):
        for field in fact_type.get("fields", []):
            types.add(field["semanticType"])
    for value_type in fact_types.get("valueTypes", []):
        types.add(value_type["id"])
    return frozenset(types)


def _legacy_documents(repo_root: Path) -> dict[str, dict[str, Any]]:
    sources = load_semantic_sources(repo_root)
    documents = {
        "registry/capabilities.yaml": dict(sources.capabilities),
        "registry/executor-bindings.yaml": dict(sources.executor_bindings),
        "ontology/fact-types.yaml": dict(sources.fact_types),
        "ontology/capability-relations.yaml": dict(sources.relations),
    }
    semantic_types_path = repo_root / "registry/semantic-types.yaml"
    if semantic_types_path.exists():
        documents["registry/semantic-types.yaml"] = load_yaml_mapping(
            semantic_types_path
        )
    return documents


def validate_structure(
    package: dict[str, Any],
    assets: Mapping[str, dict[str, Any]],
    registry_snapshot_id: str,
    repo_root: Path | None = None,
) -> StructuralValidationReport:
    """Validate one assembled package document. Collects all findings."""
    root = repo_root or REPO_ROOT
    issues: list[SemanticReleaseIssue] = []

    def issue(path: str, code: str, message: str) -> None:
        issues.append(SemanticReleaseIssue(path, code, message))

    package_schema = _load_schema(root, "semantic-release.schema.json")
    try:
        jsonschema.validate(package, package_schema)
    except jsonschema.ValidationError as exc:
        issue("$", "SR_SCHEMA_INVALID", exc.message)

    # Authored asset documents must satisfy their own strict schemas.
    asset_schemas = {
        path: _load_schema(root, schema_name)
        for path, schema_name in ASSET_SCHEMAS.items()
    }
    for path, document in assets.items():
        schema = asset_schemas.get(path)
        if schema is not None:
            try:
                jsonschema.validate(document, schema)
            except jsonschema.ValidationError as exc:
                issue(path, "SR_SCHEMA_INVALID", exc.message)

    rows = package.get("sources", [])

    seen_paths: set[str] = set()
    for row in rows:
        path = row.get("path")
        if path in seen_paths:
            issue(path or "$", "SR_DUPLICATE_SOURCE", "source listed twice")
        seen_paths.add(path)

    semantic_paths = {
        row.get("path") for row in rows if row.get("role") == "semantic"
    }
    if semantic_paths != SEMANTIC_PATHS:
        missing = sorted(SEMANTIC_PATHS - semantic_paths)
        unknown = sorted(
            path
            for path in semantic_paths - SEMANTIC_PATHS
            if path not in _LEGACY_PATHS
        )
        if missing or unknown:
            issue(
                "$.sources",
                "SR_MANIFEST_VIOLATION",
                f"missing={missing} unknown={unknown}",
            )
    for row in rows:
        if row.get("role") not in {"legacy", "semantic"}:
            issue(str(row.get("path")), "SR_MANIFEST_VIOLATION", "unknown role")
        if row.get("path") not in SEMANTIC_PATHS and row.get("path") not in _LEGACY_PATHS:
            issue(str(row.get("path")), "SR_MANIFEST_VIOLATION", "path not in manifest")

    legacy_documents = _legacy_documents(root)

    # Per-source digest verification for semantic-role and legacy documents.
    for row in rows:
        path = row.get("path")
        document = None
        if row.get("role") == "semantic" and path in assets:
            document = assets[path]
        elif row.get("role") == "legacy" and path in legacy_documents:
            document = legacy_documents[path]
        if document is not None and row.get("digest") != _sha256(document):
            issue(path, "SR_DIGEST_MISMATCH", "source digest does not match content")

    if package.get("registrySnapshotId") != registry_snapshot_id:
        issue(
            "$.registrySnapshotId",
            "SR_SNAPSHOT_ID_MISMATCH",
            "package registrySnapshotId does not match the fresh legacy snapshot",
        )

    versions = assets.get("ontology/analysis-versions.yaml", {})
    compiler_version = versions.get("compilerVersion")
    operator_versions = dict(versions.get("operatorImplementations", {}))
    semantic_rows = [row for row in rows if row.get("role") == "semantic"]
    if semantic_rows and compiler_version is not None:
        expected_id = compute_semantic_snapshot_id(
            semantic_rows, compiler_version, operator_versions
        )
        if package.get("semanticSnapshotId") != expected_id:
            issue(
                "$.semanticSnapshotId",
                "SR_DIGEST_MISMATCH",
                "semanticSnapshotId does not match recomputed content digest",
            )

    vocabulary = _collect_vocabulary(legacy_documents)

    # Allowlist references resolve against the Fact type catalog.
    fact_catalog = {
        fact_type["factTypeId"]: fact_type
        for fact_type in legacy_documents.get("ontology/fact-types.yaml", {}).get(
            "factTypes", []
        )
    }
    allowlist = assets.get("ontology/analysis-fact-fields.yaml", {})
    for entry in allowlist.get("allowlist", []):
        fact_type_id = entry.get("factTypeId")
        fact_type = fact_catalog.get(fact_type_id)
        if fact_type is None:
            issue(fact_type_id, "SR_UNKNOWN_FACT_TYPE", "fact type not in catalog")
            continue
        catalog_fields = {
            field["name"]: field["semanticType"]
            for field in fact_type.get("fields", [])
        }
        for field in entry.get("fields", []):
            if catalog_fields.get(field.get("name")) != field.get("semanticType"):
                issue(
                    f"{fact_type_id}.{field.get('name')}",
                    "SR_UNKNOWN_FIELD_REF",
                    "field triple not in Fact type catalog",
                )
            if field.get("semanticType") not in vocabulary:
                issue(
                    f"{fact_type_id}.{field.get('name')}",
                    "SR_UNKNOWN_SEMANTIC_TYPE",
                    "semantic type not in ontology vocabulary",
                )

    # Object types use ontology-vocabulary semantic types.
    object_types = assets.get("ontology/object-types.yaml", {})
    for object_type in object_types.get("objectTypes", []):
        if object_type.get("semanticType") not in vocabulary:
            issue(
                object_type.get("objectTypeId", "?"),
                "SR_UNKNOWN_SEMANTIC_TYPE",
                "object key semantic type not in vocabulary",
            )

    # Closed operator set: catalog ids and version markers agree.
    catalog_ids = {
        operator["operatorId"]
        for operator in assets.get("ontology/analysis-operators.yaml", {}).get(
            "operators", []
        )
    }
    for operator_id in sorted(catalog_ids - CLOSED_OPERATOR_IDS):
        issue(operator_id, "SR_OPERATOR_NOT_IN_CLOSED_SET", "operator not in v1 set")
    for operator_id in sorted(operator_versions.keys() - catalog_ids):
        issue(
            operator_id,
            "SR_UNKNOWN_OPERATOR",
            "version marker has no catalog operator",
        )
    for operator_id in sorted(catalog_ids - operator_versions.keys()):
        issue(
            operator_id,
            "SR_UNKNOWN_OPERATOR",
            "catalog operator has no implementation version marker",
        )
    for operator_id in sorted(operator_versions.keys() - CLOSED_OPERATOR_IDS):
        issue(
            operator_id,
            "SR_OPERATOR_NOT_IN_CLOSED_SET",
            "version marker not in v1 operator set",
        )

    # Applicability references resolve to declared Definitions.
    definitions_doc = assets.get("ontology/definitions.yaml", {})
    definition_ids = {
        definition["definitionId"]
        for definition in definitions_doc.get("definitions", [])
    }
    applicability = assets.get("ontology/definition-applicability.yaml", {})
    for declaration in applicability.get("applicability", []):
        definition_id = declaration.get("definitionId")
        if definition_id not in definition_ids:
            issue(
                definition_id,
                "SR_UNKNOWN_DEFINITION_REF",
                "definition id not in definitions catalog",
            )

    return StructuralValidationReport(valid=not issues, issues=tuple(issues))


def assess_business_validity(
    assets: Mapping[str, dict[str, Any]],
) -> BusinessValidityReport:
    """Per-declaration grounded/not_grounded state; never fails the build."""
    definitions_doc = assets.get("ontology/definitions.yaml", {})
    statuses = {
        definition["definitionId"]: definition.get("status")
        for definition in definitions_doc.get("definitions", [])
    }
    applicability = assets.get("ontology/definition-applicability.yaml", {})
    entries: list[BusinessValidityEntry] = []
    for declaration in applicability.get("applicability", []):
        definition_id = declaration["definitionId"]
        declared = declaration["status"]
        catalog_status = statuses.get(definition_id)
        state = (
            "grounded"
            if declared == "grounded" and catalog_status == "grounded"
            else "not_grounded"
        )
        entries.append(
            BusinessValidityEntry(
                definition_id=definition_id,
                declared_status=declared,
                state=state,
            )
        )
    return BusinessValidityReport(entries=tuple(entries))
