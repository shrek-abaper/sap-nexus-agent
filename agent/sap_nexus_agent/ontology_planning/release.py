"""Pin execution to the exact tracked SemanticRelease package."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sap_nexus_agent.semantic_release.assets import CLOSED_OPERATOR_IDS
from sap_nexus_agent.semantic_release.builder import build_semantic_release


class ReleaseStaleError(RuntimeError):
    """Tracked semantic-release.json does not match a fresh rebuild."""


def _deterministic_bytes(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


@dataclass(frozen=True)
class PinnedRelease:
    package: Any  # SemanticReleasePackage
    assets: Mapping[str, dict[str, Any]]
    allowlist_fields: Mapping[str, frozenset[str]]
    object_types: tuple[dict[str, Any], ...]
    operators: frozenset[str]
    compiler_version: str
    operator_versions: Mapping[str, str]


def pin_release(repo_root: Path) -> PinnedRelease:
    package = build_semantic_release(repo_root)
    artifact_path = repo_root / "ontology/generated/semantic-release.json"
    tracked_bytes = artifact_path.read_bytes()
    if tracked_bytes != _deterministic_bytes(package.to_dict()):
        raise ReleaseStaleError(
            "ontology/generated/semantic-release.json is stale; "
            "run scripts/build-semantic-release.py"
        )

    def _load(rel: str) -> dict[str, Any]:
        return yaml.safe_load((repo_root / rel).read_text(encoding="utf-8"))

    allowlist_doc = _load("ontology/analysis-fact-fields.yaml")
    allowlist_fields = {
        entry["factTypeId"]: frozenset(field["name"] for field in entry["fields"])
        for entry in allowlist_doc["allowlist"]
    }
    object_types_doc = _load("ontology/object-types.yaml")
    versions_doc = _load("ontology/analysis-versions.yaml")

    assets = {
        "ontology/analysis-fact-fields.yaml": allowlist_doc,
        "ontology/analysis-operators.yaml": _load(
            "ontology/analysis-operators.yaml"
        ),
        "ontology/analysis-versions.yaml": versions_doc,
        "ontology/object-types.yaml": object_types_doc,
    }

    return PinnedRelease(
        package=package,
        assets=assets,
        allowlist_fields=allowlist_fields,
        object_types=tuple(object_types_doc["objectTypes"]),
        operators=frozenset(CLOSED_OPERATOR_IDS),
        compiler_version=versions_doc["compilerVersion"],
        operator_versions=dict(versions_doc["operatorImplementations"]),
    )
