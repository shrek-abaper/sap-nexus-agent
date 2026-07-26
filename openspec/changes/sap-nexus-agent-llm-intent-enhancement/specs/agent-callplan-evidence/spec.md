## MODIFIED Requirements

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution. The selector SHALL emit an explicit five-state `MatchDecision` (`SELECT` / `CLARIFY` / `REJECT` / `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER`) replacing the implicit `SelectionResult`. The selector SHALL route recognized single intents to their registered capability IDs across executor types (for example `inventory_availability` -> `MM.Inventory.GetAvailability` via `JCO_RFC`, `purchase_order_list` -> `MM.PurchaseOrder.GetList` via `ODATA`) without the Agent needing to know the executor type or binding at selection time. LLM-assisted selection MUST be constrained to the same closed set and MUST NOT introduce new executable capability IDs.

The rule parser and LLM parser SHALL detect multiple intents in a single utterance. When more than one capability intent is detected, the selector MUST emit `ESCALATE_TO_PLANNER` with a record and explanation, and MUST NOT silently reduce to the first-matched single capability.

The `IntentAdapter` signature SHALL be `Callable[[str, ConversationContext | None], IntentParseResult]` with `ConversationContext` defaulting to `None`. The LLM path (`parse_with_hybrid`) SHALL be the primary intent recognizer: `_messages` MUST inject `last_context` (capability+parameters) so the LLM has complete context to resolve anaphora ("这个物料" -> prior material). The LLM result SHALL be used directly (empty/error results no longer fall back to rule); the rule path SHALL only run when the LLM is unavailable (connection failure). When the rule path runs as fallback, it SHALL inherit `last_context` material: if the utterance contains a primary keyword but the extractor cannot extract material and `last_context` has material, the adapter SHALL inherit the prior material (anaphora scenario).

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

#### Scenario: LLM resolves anaphora via last_context
- **WHEN** turn 1 "DEMOA2 在 5100..." resolves to SELECT and `last_context=SELECT(inventory, {material:DEMOA2})`
- **AND** turn 2 "这个物料在1000的库存" contains "库存" primary keyword
- **THEN** the LLM path resolves "这个物料" to `material=DEMOA2` via `last_context` injection
- **AND** emits `SELECT` with `material=DEMOA2, plant=1000`

#### Scenario: Rule fallback inherits material on primary keyword
- **WHEN** the LLM is unavailable and the rule path runs
- **AND** the utterance contains a primary keyword but extractor cannot extract material
- **AND** `last_context` has material
- **THEN** the adapter inherits the prior material and proceeds to SELECT or CLARIFY

## ADDED Requirements

### Requirement: Multi-plant query split
The orchestrator SHALL support multi-plant inventory queries. When the LLM identifies multiple plants in a single utterance (e.g. "5200、1000的库存分别是多少"), the orchestrator SHALL split into multiple single-plant execute calls (one per plant) and aggregate the results. The capability contract (single plant) SHALL NOT change. Partial failures (one plant fails) SHALL be surfaced as partial results with the failed plant annotated.

#### Scenario: Multi-plant query splits and aggregates
- **WHEN** the user asks "这个物料在5200、1000的库存分别是多少" (same conversation, last_context has material)
- **THEN** the LLM identifies plants [5200, 1000]
- **AND** the orchestrator executes MM.Inventory.GetAvailability twice (plant=5200, plant=1000)
- **AND** aggregates results into a single narrative: "5200: 176 EA; 1000: 0 EA"

#### Scenario: Multi-plant partial failure
- **WHEN** one plant execute fails (SAP error) in a multi-plant query
- **THEN** the orchestrator returns partial results with the failed plant annotated
- **AND** does not fail the entire query
