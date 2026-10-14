"""Ontology-constrained dynamic read-only analysis (C2).

Server-owned, deterministic, offline-by-default goal resolution, plan
compilation, fact normalization, and registered-operator analysis. The
LLM/interpreter produces only an untrusted SemanticGoalDraft; execution is
authorized solely by server-side compilation against a pinned SemanticRelease.
"""

from __future__ import annotations

from .bounds import BOUNDS, Bounds
from .contracts import (
    AnalysisNodeDraft,
    ObjectSelector,
    RequestedConclusion,
    RequestedFact,
    SemanticGoalDraft,
    TypedConstraint,
)

__all__ = [
    "BOUNDS",
    "Bounds",
    "AnalysisNodeDraft",
    "ObjectSelector",
    "RequestedConclusion",
    "RequestedFact",
    "SemanticGoalDraft",
    "TypedConstraint",
]
