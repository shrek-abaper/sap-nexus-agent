"""MatchDecision dataclass and five-state DecisionType (S2-A, Plan Task 1).

Replaces the implicit three-state SelectionResult with an explicit five-state
decision object so the orchestrator can express SHOW_OPTIONS (ambiguous
candidates) and ESCALATE_TO_PLANNER (multi-intent / composition required),
which the previous SelectionResult could not represent.

Design Doc: docs/superpowers/specs/2026-07-25-sap-nexus-planner-dry-run-design.md
section "MatchDecision 对象".

SelectionResult is retained as a narrow-view compat wrapper: SELECT / CLARIFY
/ REJECT map onto it via ``to_selection_result()``; SHOW_OPTIONS and
ESCALATE_TO_PLANNER return ``None`` (the orchestrator inspects ``decision_type``
directly). One release cycle of compat, then evaluate removal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sap_nexus_agent.capability_selector import SelectionResult

DecisionType = Literal[
    "SELECT",
    "CLARIFY",
    "REJECT",
    "SHOW_OPTIONS",
    "ESCALATE_TO_PLANNER",
]


@dataclass(frozen=True)
class MatchedIntent:
    """One capability match extracted from the utterance.

    ``missing`` is the list of required parameters the utterance did not
    provide; empty when the match is fully parameterised.
    """

    capability_id: str
    parameters: dict[str, str]
    missing: list[str]


@dataclass(frozen=True)
class EscalationHandoff:
    """Payload handed to the planner when ESCALATE_TO_PLANNER is chosen.

    Carries enough context for the planner to compose capabilities without
    re-parsing the utterance: why we escalated, every matched intent, the
    original utterance, and the registry snapshot id the matches were made
    against (so the planner sees the same capability cards).
    """

    reason: str
    matched_intents: list[MatchedIntent]
    utterance: str
    registry_snapshot_id: str


@dataclass(frozen=True)
class MatchDecision:
    """Explicit five-state capability match decision.

    Per-state required fields (caller's responsibility to populate):

    - ``SELECT``              -> ``capability_id`` + ``parameters``
    - ``CLARIFY``             -> ``missing_parameters``
    - ``REJECT``              -> ``error_type``
    - ``SHOW_OPTIONS``        -> ``candidates``
    - ``ESCALATE_TO_PLANNER`` -> ``handoff``
    """

    decision_type: DecisionType
    capability_id: str | None = None  # SELECT
    parameters: dict[str, str] | None = None  # SELECT
    missing_parameters: list[str] | None = None  # CLARIFY
    error_type: str | None = None  # REJECT
    candidates: list[MatchedIntent] | None = None  # SHOW_OPTIONS
    handoff: EscalationHandoff | None = None  # ESCALATE_TO_PLANNER
    rationale: str = ""

    def to_selection_result(self) -> SelectionResult | None:
        """Narrow-view compat: map onto the legacy SelectionResult.

        Returns a SelectionResult for SELECT / CLARIFY / REJECT so existing
        orchestrator callers keep working during the migration. Returns
        ``None`` for SHOW_OPTIONS and ESCALATE_TO_PLANNER - callers must
        inspect ``decision_type`` for those states.
        """
        if self.decision_type == "SELECT":
            return SelectionResult(capability_id=self.capability_id)
        if self.decision_type == "CLARIFY":
            return SelectionResult(
                capability_id=None,
                error_type="MISSING_PARAMETER",
                message=self.rationale,
            )
        if self.decision_type == "REJECT":
            return SelectionResult(
                capability_id=None,
                error_type=self.error_type,
                message=self.rationale,
            )
        return None  # SHOW_OPTIONS / ESCALATE_TO_PLANNER
