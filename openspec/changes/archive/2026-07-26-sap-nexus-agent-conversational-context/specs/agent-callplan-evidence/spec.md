## MODIFIED Requirements

### Requirement: Missing parameter clarification
The system MUST clarify missing required inventory parameters before any Gateway validate or execute call, whether missing parameters are detected by rules or by LLM output. When a `ConversationContext` with a `LastContext(decision_type=CLARIFY)` is supplied, the intent adapter SHALL apply sticky cross-turn slot-filling per the `conversational-context` capability: a follow-up utterance with no capability primary keyword SHALL be treated as a slot-fill answer for the pending `capability_id`, merging extracted parameters and re-evaluating `missing_parameters` before deciding whether to emit `CLARIFY` or `SELECT`. When no `ConversationContext` is supplied (default `None`), the adapter SHALL behave as single-turn (backward compatible).

#### Scenario: LLM missing plant is clarified before Gateway call
- **WHEN** the LLM identifies inventory availability intent but omits `plant`
- **THEN** the Agent returns a Chinese clarification asking for `plant`
- **AND** the Agent does not call Gateway validate or execute

#### Scenario: Slot-fill across turns resolves to SELECT
- **WHEN** a `ConversationContext` carries `PendingClarification(capability_id=MM.Inventory.GetAvailability, missing=[material, plant])`
- **AND** the follow-up utterance "DEMOA2 1000" contains no capability primary keyword
- **THEN** the adapter re-runs the inventory extractor, merges `material=DEMOA2` and `plant=1000`
- **AND** emits a complete intent result that leads to `SELECT` (no `CLARIFY`)

#### Scenario: Single-turn fallback when context is None
- **WHEN** no `ConversationContext` is supplied
- **THEN** the adapter parses the utterance as a standalone single-turn input
- **AND** does not perform any cross-turn slot-filling

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution. The selector SHALL emit an explicit five-state `MatchDecision` (`SELECT` / `CLARIFY` / `REJECT` / `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER`) replacing the implicit `SelectionResult`. The selector SHALL route recognized single intents to their registered capability IDs across executor types (for example `inventory_availability` -> `MM.Inventory.GetAvailability` via `JCO_RFC`, `purchase_order_list` -> `MM.PurchaseOrder.GetList` via `ODATA`) without the Agent needing to know the executor type or binding at selection time. LLM-assisted selection MUST be constrained to the same closed set and MUST NOT introduce new executable capability IDs.

The rule parser and LLM parser SHALL detect multiple intents in a single utterance. When more than one capability intent is detected, the selector MUST emit `ESCALATE_TO_PLANNER` with a record and explanation, and MUST NOT silently reduce to the first-matched single capability.

The `IntentAdapter` signature SHALL be `Callable[[str, ConversationContext | None], IntentParseResult]` with `ConversationContext` defaulting to `None`, so existing single-turn callers and tests remain unchanged. When `ConversationContext.pending_clarification` is present and the current utterance contains no capability primary keyword, the selector input reflects the merged slot-fill result rather than a fresh empty parse.

#### Scenario: Route single inventory intent to SELECT
- **WHEN** the parser identifies a single `inventory_availability` intent with required `material` and `plant`
- **THEN** the Agent emits `MatchDecision.decision_type=SELECT` for `capabilityId=MM.Inventory.GetAvailability` and proceeds to CallPlan and Gateway validation
- **AND** the Agent does not choose an executor type or binding at selection time

#### Scenario: Route single purchase order intent to SELECT
- **WHEN** the parser identifies a single `purchase_order_list` intent with at least one filter parameter
- **THEN** the Agent emits `MatchDecision.decision_type=SELECT` for `capabilityId=MM.PurchaseOrder.GetList` and proceeds to CallPlan and Gateway validation

#### Scenario: Multi-goal utterance escalates to planner
- **WHEN** the parser detects both inventory availability and purchase order list intents in one utterance
- **THEN** the Agent emits `MatchDecision.decision_type=ESCALATE_TO_PLANNER` with a record and explanation
- **AND** the Agent does NOT silently select the first-matched capability or call Gateway validate or execute

#### Scenario: LLM selects registered capability only
- **WHEN** the LLM returns a single `capabilityId=MM.Inventory.GetAvailability` or `MM.PurchaseOrder.GetList` with required parameters
- **THEN** the Agent accepts the candidate only after deterministic validation confirms the closed-set capability and emits `SELECT`

#### Scenario: LLM returns unknown capability
- **WHEN** the LLM returns an unknown or unsupported `capabilityId`
- **THEN** the Agent emits `MatchDecision.decision_type=REJECT` and does not call Gateway validate or execute

#### Scenario: False SELECT fails regression
- **WHEN** a multi-goal utterance is silently reduced to a single `SELECT`
- **THEN** the matcher Eval marks this as a regression failure

#### Scenario: IntentAdapter accepts optional ConversationContext
- **WHEN** the orchestrator calls `intent_adapter(text, context)` with a non-None `ConversationContext`
- **THEN** the adapter applies sticky-CLARIFY slot-filling using `context.pending_clarification`
- **AND** when called as `intent_adapter(text)` or `intent_adapter(text, None)` the adapter behaves as single-turn (backward compatible)
