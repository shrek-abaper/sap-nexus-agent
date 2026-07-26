## MODIFIED Requirements

### Requirement: Closed-set capability selection
The system SHALL select capabilities only from the Registry closed set and MUST reject unsupported intent before Gateway execution. The selector SHALL emit an explicit five-state `MatchDecision` (`SELECT` / `CLARIFY` / `REJECT` / `SHOW_OPTIONS` / `ESCALATE_TO_PLANNER`) replacing the implicit `SelectionResult`. The selector SHALL route recognized single intents to their registered capability IDs across executor types (for example `inventory_availability` -> `MM.Inventory.GetAvailability` via `JCO_RFC`, `purchase_order_list` -> `MM.PurchaseOrder.GetList` via `ODATA`) without the Agent needing to know the executor type or binding at selection time. LLM-assisted selection MUST be constrained to the same closed set and MUST NOT introduce new executable capability IDs.

The rule parser and LLM parser SHALL detect multiple intents in a single utterance. When more than one capability intent is detected, the selector MUST emit `ESCALATE_TO_PLANNER` with a record and explanation, and MUST NOT silently reduce to the first-matched single capability.

The `IntentAdapter` signature SHALL be `Callable[[str, ConversationContext | None], IntentParseResult]` with `ConversationContext` defaulting to `None`. The LLM path (`parse_with_hybrid`) SHALL be the primary intent recognizer: `_messages` MUST inject `last_context` (capability+parameters) so the LLM has complete context to resolve anaphora ("这个物料" -> prior material). The LLM result SHALL be used directly (empty/error results no longer fall back to rule); the rule path SHALL only run when the LLM is unavailable (connection failure). When the rule path runs as fallback, it SHALL inherit `last_context` material: if the utterance contains a primary keyword but the extractor cannot extract material and `last_context` has material, the adapter SHALL inherit the prior material (anaphora scenario).

When the LLM is available but returns no capabilityId (empty/ambiguous result, not a connection failure), the adapter SHALL populate a generic clarification and the selector SHALL emit `CLARIFY` (not `REJECT`); the rule path's empty return (no clarification) still maps to `REJECT`. The `IntentParseResult` SHALL carry a `multi_parameters: dict[str, list[str]]` field (default empty) for multi-valued parameters. When the user mentions multiple values for any parameter, the LLM SHALL return them in a `multiParameters` JSON array (not in `parameters`); single-valued parameters remain in `parameters`. The selector SHALL treat a required parameter as satisfied if it is present in `parameters` OR `multi_parameters`, so a multi-valued required parameter does not trigger `CLARIFY`.

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

#### Scenario: LLM empty return emits CLARIFY
- **WHEN** the LLM is available but returns no capabilityId (empty/ambiguous result)
- **THEN** the adapter populates a generic clarification
- **AND** the selector emits `MatchDecision.decision_type=CLARIFY` (not REJECT)

#### Scenario: Multi-value parameter emits SELECT with multi_parameters
- **WHEN** the LLM returns `multi_parameters={"plant":["5200","1000"]}` for a single matched capability
- **AND** all required parameters are satisfied across `parameters` and `multi_parameters`
- **THEN** the selector emits `MatchDecision.decision_type=SELECT` (multi_parameters carried on IntentParseResult)
- **AND** does NOT emit CLARIFY for the multi-valued parameter

## ADDED Requirements

### Requirement: Multi-value query split
The orchestrator SHALL support multi-value inventory queries where any parameter (e.g. `plant`, `material`) has multiple values. When the LLM identifies multiple values for one or more parameters in a single utterance (e.g. "DEMOA2 和 DEMOA4 在 5200、1000 的库存"), the orchestrator SHALL expand the Cartesian product of the multi-valued parameters (via `multi_parameters`) into a combination list and return `AgentOutcome.status="awaiting_batch_confirm"` with the combinations. The orchestrator SHALL NOT execute Gateway calls until the user confirms. Upon confirmation, `continue_batch` SHALL execute single-value execute calls per combination (the single-plant/single-material capability contract SHALL NOT change) and aggregate the results. Partial failures (one combination fails) SHALL be surfaced as partial results with the failed combination annotated. A soft combination cap (default 20) SHALL emit CLARIFY when exceeded, instead of `awaiting_batch_confirm`.

#### Scenario: Multi-value query emits awaiting_batch_confirm
- **WHEN** the user asks "DEMOA2 和 DEMOA4 在 5200、1000 的库存分别是多少" (same conversation)
- **THEN** the LLM returns `multi_parameters={plant:[5200,1000], material:[DEMOA2,DEMOA4]}`
- **AND** the orchestrator expands 4 combinations (2×2 Cartesian product)
- **AND** returns `awaiting_batch_confirm` with the 4 combinations and does NOT call Gateway validate or execute

#### Scenario: Confirmed multi-value batch executes and aggregates
- **WHEN** the user confirms the batch from a prior `awaiting_batch_confirm` outcome
- **THEN** `continue_batch` executes MM.Inventory.GetAvailability once per combination
- **AND** aggregates results into a single narrative: "5200: 176 EA; 1000: 0 EA" (single material) or a per-material narrative (multi material)

#### Scenario: Multi-value partial failure
- **WHEN** one combination execute fails (SAP error) in a confirmed batch
- **THEN** `continue_batch` returns partial results with the failed combination annotated
- **AND** does not fail the entire batch

#### Scenario: Multi-value combination cap
- **WHEN** the expanded combinations exceed the soft cap (default 20)
- **THEN** the orchestrator emits CLARIFY "组合数过多，请缩小范围" instead of `awaiting_batch_confirm`
- **AND** does NOT execute any Gateway call
