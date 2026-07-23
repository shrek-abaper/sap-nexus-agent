from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .contracts import SemanticSourceDocuments


class SourceLoadError(ValueError):
    def __init__(self, path: Path, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourceLoadError(path, str(exc)) from exc
    if not isinstance(value, dict):
        raise SourceLoadError(path, "document root must be a mapping")
    return value


def load_semantic_sources(repo_root: Path) -> SemanticSourceDocuments:
    return SemanticSourceDocuments(
        capabilities=load_yaml_mapping(repo_root / "registry/capabilities.yaml"),
        executor_bindings=load_yaml_mapping(
            repo_root / "registry/executor-bindings.yaml"
        ),
        fact_types=load_yaml_mapping(repo_root / "ontology/fact-types.yaml"),
        relations=load_yaml_mapping(repo_root / "ontology/capability-relations.yaml"),
    )
