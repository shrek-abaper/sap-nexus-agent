"""Server-owned, versioned bounds for ontology-governed read analysis.

These constants cannot be overridden by requests, drafts, or models.
Changing a bound is a compiler-semantics change: bump ``compilerVersion``
in ``ontology/analysis-versions.yaml`` (a covered SemanticRelease source)
in the same change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bounds:
    max_read_nodes: int = 6
    max_analysis_nodes: int = 6
    max_depth: int = 4
    max_model_turns: int = 2
    overall_timeout_seconds: int = 90
    max_rows: int = 5000
    max_response_bytes: int = 2 * 1024 * 1024
    max_draft_bytes: int = 256 * 1024
    max_string_chars: int = 4096
    max_nesting_depth: int = 8
    max_requested_facts: int = 6


BOUNDS = Bounds()
