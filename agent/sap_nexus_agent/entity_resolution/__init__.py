"""Ontology-driven master-data entity resolution.

Logical rules are declared in ``ontology/entity-resolution.yaml`` and
cross-validated against object types and the capability registry by
``rules.validate_rules``. Physical mapping, SQL, and credentials never
appear here; they live in trusted server-side Provider configuration.
"""

from __future__ import annotations

from .rules import (
    EntityResolutionRule,
    ResolutionIssue,
    load_resolution_rules,
    validate_rules,
)

__all__ = [
    "EntityResolutionRule",
    "ResolutionIssue",
    "load_resolution_rules",
    "validate_rules",
]
