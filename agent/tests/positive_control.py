"""Loader for the data dependency deriver's positive-control fixture (task 3.2).

Not a test module — pytest does not collect it. It exists so the fabricated
capability pair has exactly one authority. Inlining the same pair into two test
modules would be precisely the field-list restatement this change is removing.

Every call re-reads and re-parses the YAML, so callers may mutate what they get
back without leaking state into the next test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sap_nexus_agent.semantic_planning import SemanticSourceDocuments

POSITIVE_CONTROL_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "semantic_planning"
    / "derivation-positive-control.yaml"
)

#: Every fabricated id carries one of these prefixes, so contamination of a
#: governed source is detectable by shape rather than by remembering the ids.
FABRICATED_CAPABILITY_PREFIX = "T."
FABRICATED_ONTOLOGY_PREFIX = "test:"


def load_positive_control() -> dict[str, Any]:
    """The parsed fixture: ``{"capabilities": <doc>, "factTypes": <doc>}``."""
    return yaml.safe_load(POSITIVE_CONTROL_PATH.read_text(encoding="utf-8"))


def positive_control_documents(
    capabilities: list[dict[str, Any]] | None = None,
    fact_types: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
) -> SemanticSourceDocuments:
    """The fixture as `SemanticSourceDocuments`, optionally with substitutions.

    `executor_bindings` is empty, and `relations` is empty unless a caller
    supplies one: the deriver reads neither, and supplying plausible-looking
    values would suggest otherwise. The `relations` parameter exists for the
    task-3.3 tests, which feed the *rendered* derived relations back to a reader
    to check that it consumes them.
    """
    fixture = load_positive_control()
    capabilities_document = fixture["capabilities"]
    fact_types_document = fixture["factTypes"]
    if capabilities is not None:
        capabilities_document = {**capabilities_document, "capabilities": capabilities}
    if fact_types is not None:
        fact_types_document = {**fact_types_document, "factTypes": fact_types}
    return SemanticSourceDocuments(
        capabilities=capabilities_document,
        executor_bindings={"version": 1, "executorBindings": []},
        fact_types=fact_types_document,
        relations={"version": 1, "relations": relations or []},
    )


def positive_control_capabilities() -> list[dict[str, Any]]:
    return load_positive_control()["capabilities"]["capabilities"]


def positive_control_fact_types() -> list[dict[str, Any]]:
    return load_positive_control()["factTypes"]["factTypes"]


def positive_control_capability(capability_id: str) -> dict[str, Any]:
    return next(
        item
        for item in positive_control_capabilities()
        if item["capabilityId"] == capability_id
    )


def positive_control_fact_type(fact_type_id: str) -> dict[str, Any]:
    return next(
        item
        for item in positive_control_fact_types()
        if item["factTypeId"] == fact_type_id
    )
