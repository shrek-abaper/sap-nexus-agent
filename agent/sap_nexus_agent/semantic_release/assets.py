"""Closed source manifest and loading for SemanticRelease semantic assets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sap_nexus_agent.semantic_planning.loader import load_yaml_mapping

# Logical paths covered by semanticSnapshotId with role "semantic".
# Closed by design: adding a covered source is a reviewed change to this
# tuple, never a silent directory scan.
SEMANTIC_SOURCE_MANIFEST: tuple[tuple[str, str], ...] = (
    ("ontology/analysis-fact-fields.yaml", "semantic"),
    ("ontology/analysis-operators.yaml", "semantic"),
    ("ontology/analysis-versions.yaml", "semantic"),
    ("ontology/definition-applicability.yaml", "semantic"),
    ("ontology/object-types.yaml", "semantic"),
    ("ontology/definitions.yaml", "semantic"),
    ("ontology/object-links.yaml", "semantic"),
    ("ontology/business-rules.yaml", "semantic"),
)

# Legacy RegistrySnapshot documents (role "legacy"). The digest convention
# matches semantic_planning.snapshot via documents_by_path(); semantic-types
# participates when present.
LEGACY_SOURCE_PATHS: tuple[str, ...] = (
    "registry/capabilities.yaml",
    "registry/executor-bindings.yaml",
    "ontology/fact-types.yaml",
    "ontology/capability-relations.yaml",
    "registry/semantic-types.yaml",
)

# Authored asset document -> JSON Schema file under schemas/.
ASSET_SCHEMAS: dict[str, str] = {
    "ontology/analysis-fact-fields.yaml": "analysis-fact-fields.schema.json",
    "ontology/analysis-operators.yaml": "analysis-operators.schema.json",
    "ontology/analysis-versions.yaml": "analysis-versions.schema.json",
    "ontology/definition-applicability.yaml": "definition-applicability.schema.json",
    "ontology/object-types.yaml": "object-types.schema.json",
}

CLOSED_OPERATOR_IDS: frozenset[str] = frozenset(
    {"select_fields", "filter_eq", "group_sum", "compare"}
)


def load_release_assets(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Load every semantic-role manifest document keyed by logical path."""
    return {
        path: load_yaml_mapping(repo_root / path)
        for path, _role in SEMANTIC_SOURCE_MANIFEST
    }
