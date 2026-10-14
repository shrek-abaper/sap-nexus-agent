"""SemanticRelease v1 asset pipeline (C1)."""

from __future__ import annotations

from .builder import build_semantic_release
from .contracts import (
    BusinessValidityEntry,
    BusinessValidityReport,
    ReleaseSource,
    SemanticReleaseIssue,
    SemanticReleasePackage,
    StructuralValidationReport,
    STRUCTURAL_ISSUE_CODES,
)
from .validation import assess_business_validity, validate_structure

__all__ = [
    "BusinessValidityEntry",
    "BusinessValidityReport",
    "ReleaseSource",
    "SemanticReleaseIssue",
    "SemanticReleasePackage",
    "StructuralValidationReport",
    "STRUCTURAL_ISSUE_CODES",
    "assess_business_validity",
    "build_semantic_release",
    "validate_structure",
]
