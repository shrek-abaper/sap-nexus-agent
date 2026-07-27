# agent-callplan-evidence Specification

## Purpose
TBD - created by archiving change sap-nexus-agent-callplan-evidence. Update Purpose after archive.
## Requirements
### Requirement: Chinese inventory intent parsing
The system SHALL parse Chinese inventory availability queries for `MM.Inventory.GetAvailability` into normalized intent parameters without using free-form RFC names. The parser MAY use a real LLM intent adapter before deterministic validation, but the LLM output is advisory and MUST be normalized into the same closed-set intent contract before capability selection.

#### Scenario: Parse complete inventory availability query with LLM adapter
- **WHEN** hybrid intent mode is enabled and the LLM returns trusted JSON for `DEMOA1 在 1000 还有多少可用库存？`
- **THEN** the Agent identifies inventory availability intent and extracts `material=DEMOA1` and `plant=1000`
- **AND** the Agent proceeds through deterministic closed-set capability selection before Gateway validation

#### Scenario: Fall back to rule parser when LLM is unavailable
- **WHEN** hybrid intent mode is enabled and the LLM client is missing configuration, times out, returns malformed JSON, or cannot be reached
- **THEN** the Agent falls back to the existing deterministic rule parser
- **AND** executable rule-parser results still follow the normal CallPlan and Gateway path

#### Scenario: Reject LLM-generated RFC name
- **WHEN** the LLM returns JSON containing `rfcName` or a raw SAP BAPI/RFC identifier
- **THEN** the Agent treats the output as untrusted and does not execute from that LLM output
- **AND** Gateway validate and execute are not called unless a safe fallback parser independently produces a valid closed-set capability request

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

### Requirement: CallPlan before Gateway execution
The system SHALL create a structured CallPlan before Gateway validation or execution for every executable request.

#### Scenario: Complete request creates CallPlan before validate
- **WHEN** a complete inventory availability request is executable
- **THEN** the Agent creates a CallPlan containing `traceId`, `capabilityId=MM.Inventory.GetAvailability`, `kind=Function`, normalized parameters, validation policy, creator, and approval requirement before Gateway validate

#### Scenario: CallPlan is read-only
- **WHEN** the Agent creates a CallPlan for `MM.Inventory.GetAvailability`
- **THEN** the CallPlan records `requiresApproval=false` and contains no SAP write action fields

### Requirement: Gateway validate and execute orchestration
The system SHALL call the Java Gateway capability APIs by `capabilityId` and handle validation or execution failure as structured Agent outcomes.

#### Scenario: Valid request calls Gateway validate then execute
- **WHEN** Gateway validate succeeds for a complete CallPlan
- **THEN** the Agent calls Gateway execute for `MM.Inventory.GetAvailability` and parses the returned `ExecutionResult`

#### Scenario: Gateway validation failure stops execution
- **WHEN** Gateway validate returns `INVALID_PARAMETER` or `MISSING_PARAMETER`
- **THEN** the Agent returns a structured Chinese failure response and does not call Gateway execute

#### Scenario: Gateway execution failure is reported without secrets
- **WHEN** Gateway execute returns a failed `ExecutionResult`
- **THEN** the Agent reports the failure using `errorType` and safe return messages without exposing SAP passwords, destination config, tokens, or `.env` contents

### Requirement: ExecutionResult to ReasoningFact conversion
The system SHALL convert successful inventory `ExecutionResult` data into deterministic `ReasoningFact` evidence before narration.

#### Scenario: Successful execution creates availability fact
- **WHEN** Gateway execute returns success with `data.availableQuantity`, `data.material`, `data.plant`, and optional MD04 evidence fields derived from `MRP_IND_LINES`
- **THEN** the Agent creates a `ReasoningFact` with `predicate=availableQuantity`, `deterministic=true`, `confidence=1.0`, source capability metadata, and evidence fields for the returned quantity and source field
- **AND** the Chinese narrative uses the normalized `availableQuantity` without exposing raw SAP table contents or credentials

#### Scenario: Failed execution does not create success fact
- **WHEN** Gateway execute returns `success=false`
- **THEN** the Agent does not create a deterministic availability fact that claims a successful quantity

### Requirement: Chinese narration from facts only

The system SHALL render Chinese narrative only from fields present in `ReasoningFact` or structured failure outcomes. When the LLM narration path is used, the LLM SHALL be constrained (via prompt and output redaction) to use only the provided fact fields and MUST NOT invent records, values, or fields; when the LLM is unavailable the system SHALL fall back to deterministic template narration grounded on the same fact fields.

#### Scenario: Narrate available quantity from fact

- **WHEN** a `ReasoningFact` contains material, plant, available quantity, and unit
- **THEN** the Chinese answer includes only those fact values and does not invent additional stock, demand, recommendation, or write-action details

#### Scenario: Narrator rejects missing fact values

- **WHEN** the narrator is asked to output a quantity that is not present in `ReasoningFact`
- **THEN** the Agent returns or raises a narrative guard failure (or falls back to template) instead of inventing the value

### Requirement: Eval and trace evidence
The system SHALL provide repeatable fast eval coverage for the read-only Agent MVP and keep generated runtime evidence out of git. Normal verification MUST NOT require live LLM network access or real model credentials.

#### Scenario: Fake LLM eval covers hybrid behavior
- **WHEN** the Agent test suite runs without live LLM credentials
- **THEN** fake LLM cases verify happy path, missing params, fallback, unknown capability, malformed JSON, and `rfcName` guard behavior

#### Scenario: Optional live LLM smoke is explicitly gated
- **WHEN** live LLM smoke tests exist
- **THEN** they run only when an explicit environment flag is set
- **AND** they skip by default without printing API keys, full model gateway config, or raw sensitive response content

### Requirement: Purchase order list intent parsing
The system SHALL parse Chinese purchase order list queries for `MM.PurchaseOrder.GetList` into normalized intent parameters without using free-form RFC names or raw OData endpoints. The parser MAY use the real LLM intent adapter before deterministic validation, but the LLM output is advisory and MUST be normalized into the same closed-set intent contract before capability selection.

#### Scenario: Parse purchase order query with vendor filter
- **WHEN** the user asks `查供应商 DEMOV1 的采购订单`
- **THEN** the Agent identifies `purchase_order_list` intent and extracts `vendor=DEMOV1`
- **AND** the Agent proceeds through deterministic closed-set capability selection before Gateway validation

#### Scenario: Parse purchase order query with multiple filters
- **WHEN** the user asks `查工厂 1000 物料 MAT001 的采购订单`
- **THEN** the Agent identifies `purchase_order_list` intent and extracts plant and material parameters
- **AND** the Agent maps the parameters to the registered `$filter` fields through the capability contract, not by emitting a raw OData `$filter` string

#### Scenario: Clarify missing filter before Gateway call
- **WHEN** the user asks `帮我看看采购订单` without any of PO number, vendor, plant/purchasing group, or material
- **THEN** the Agent returns a Chinese clarification asking for at least one filter parameter
- **AND** the Agent does not call Gateway validate or execute

#### Scenario: Reject raw OData endpoint in user or LLM input
- **WHEN** the user or LLM output contains a raw OData URL, service path, or `$filter` string
- **THEN** the Agent treats the input as untrusted and does not execute from it
- **AND** Gateway validate and execute are not called unless a safe fallback parser independently produces a valid closed-set capability request

### Requirement: List execution result to reasoning facts

The system SHALL convert a successful list-shaped `ExecutionResult` into one or more deterministic `ReasoningFact` entries before narration, with one fact per returned item, and MUST narrate list results only from fields present in those facts. When the LLM narration path is used, the LLM SHALL be constrained to cite only item fields present in the facts and MUST NOT invent additional records or quantities; when the LLM is unavailable the system SHALL fall back to deterministic template narration.

#### Scenario: Successful list execution creates per-item facts

- **WHEN** Gateway execute returns success with a non-empty `purchaseOrders` array for `MM.PurchaseOrder.GetList`
- **THEN** the Agent creates one `ReasoningFact` per purchase order item with `predicate=purchaseOrderItem`, `deterministic=true`, `confidence=1.0`, source capability metadata, and per-item evidence fields
- **AND** the Chinese narrative cites only those item fields present in the facts and does not invent additional records

#### Scenario: Empty list execution creates no item facts

- **WHEN** Gateway execute returns success with an empty `purchaseOrders` array for a valid filter
- **THEN** the Agent does not create per-item facts that claim records exist
- **AND** the Chinese narrative states that no matching purchase orders were found

#### Scenario: Narrator rejects list item values not present in facts

- **WHEN** the narrator is asked to output a PO number, vendor, or quantity that is not present in any `ReasoningFact`
- **THEN** the Agent returns or raises a narrative guard failure (or falls back to template) instead of inventing the value

### Requirement: Purchase order ExecutionResult to ReasoningFact conversion with nested items

The system SHALL convert a successful purchase order `ExecutionResult` into one `ReasoningFact` per purchase order item, handling the real OData nested structure where item-level fields (`plant`, `material`, `orderQuantity`, `purchaseOrderUnit`) are nested inside a `header.items[]` sub-array. The system SHALL also remain backward-compatible with the flat shape where all fields sit directly on the purchase order entry.

#### Scenario: Nested OData items produce one fact per item

- **WHEN** a successful purchase order execution returns `purchaseOrders` where each entry has a nested `items` array
- **THEN** the Agent creates one `ReasoningFact` per item
- **AND** each fact's evidence carries `purchaseOrder` and `supplier` from the header entry
- **AND** each fact's evidence carries `plant`, `material`, `orderQuantity`, `purchaseOrderUnit` from the nested item
- **AND** the Chinese narrative lists each item without a narrative guard failure

#### Scenario: Flat purchase order entries remain supported

- **WHEN** a successful purchase order execution returns `purchaseOrders` where each entry carries all fields directly (no `items` array)
- **THEN** the Agent creates one `ReasoningFact` per purchase order entry using the entry's own fields
- **AND** existing flat-shape behavior is preserved

#### Scenario: Empty nested items yield no fact for that purchase order

- **WHEN** a purchase order entry has an empty `items` array
- **THEN** the Agent creates no `ReasoningFact` for that entry
- **AND** if all entries have empty items, the narrator returns the no-match message

### Requirement: LLM-grounded flexible narration

The system SHALL render Chinese narrative by grounding a Large Language Model on `ReasoningFact` fields and capability metadata, rather than only fixed string templates. The LLM narration prompt SHALL be derived from the capability's `businessObject`/`capabilityId` metadata so that a newly registered capability gets LLM narration without hardcoding a narration template. The system SHALL constrain the LLM to use only the provided fact fields and MUST NOT allow it to invent records, values, or fields not present in the facts.

#### Scenario: Inventory narration generated by LLM

- **WHEN** a `ReasoningFact` for `MM.Inventory.GetAvailability` carries material, plant, available quantity, and unit
- **THEN** the LLM generates a natural-language Chinese conclusion grounded on those fact fields
- **AND** the conclusion does not invent additional stock, demand, recommendation, or write-action details
- **AND** the conclusion does not expose raw SAP table contents or credentials

#### Scenario: Purchase order list narration generated by LLM

- **WHEN** one or more `ReasoningFact` entries for `MM.PurchaseOrder.GetList` carry per-item evidence
- **THEN** the LLM generates a natural-language Chinese summary grounded on those fact fields
- **AND** the summary cites only item fields present in the facts and does not invent additional records or quantities

#### Scenario: Newly registered capability gets LLM narration without template code

- **WHEN** a new capability is registered as `status: active` with a `businessObject` and outputs
- **AND** no narration-recognition code is changed
- **THEN** the LLM narration path can narrate that capability's facts using the derived guidance
- **AND** does not require a hardcoded narration template for the new capability

#### Scenario: LLM narration falls back to template when LLM unavailable

- **WHEN** the LLM is unavailable (missing configuration or connection failure) during narration
- **THEN** the Agent falls back to deterministic template narration grounded on the fact fields
- **AND** does not fail the run solely because the LLM is unavailable

#### Scenario: Empty result narration

- **WHEN** narration is requested for an empty fact list (no matching records)
- **THEN** the narrative states that no matching records were found
- **AND** does not invoke the LLM to invent records

### Requirement: Multi-value query split
The orchestrator SHALL support multi-value inventory queries where any parameter (e.g. `plant`, `material`) has multiple values. When the LLM identifies multiple values for one or more parameters in a single utterance (e.g. "DEMOA2 和 DEMOA4 在 5200、1000 的库存"), the orchestrator SHALL expand the Cartesian product of the multi-valued parameters (via `multi_parameters`) into a combination list and return `AgentOutcome.status="awaiting_batch_confirm"` with the combinations. The orchestrator SHALL NOT execute Gateway calls until the user confirms. Upon confirmation, `continue_batch` SHALL execute single-value execute calls per combination (the single-plant/single-material capability contract SHALL NOT change) and aggregate the results. Partial failures (one combination fails) SHALL be surfaced as partial results with the failed combination annotated. A soft combination cap (default 20) SHALL emit CLARIFY when exceeded, instead of `awaiting_batch_confirm`.

The workbench SHALL clear the session `last_context` (emit `None`) for an `awaiting_batch_confirm` outcome, so the LLM does not re-emit `multi_parameters` from the prior SELECT's material on the user's confirmation reply (which would loop back to `awaiting_batch_confirm`).

The workbench SHALL serialize the `combinations` and `callPlan` for an `awaiting_batch_confirm` outcome so the frontend can hold them pending user confirmation. Upon user confirmation, the service layer SHALL route a `BatchContinuation` (carrying `callPlan` + `combinations`) to `continue_batch`; this is analogous to the `continue_action` approval flow where the frontend holds `approvalRecord` and returns an `ApprovalContinuation`. `continue_batch` is READ-only (Action capabilities MUST NOT enter this path).

#### Scenario: Multi-value query emits awaiting_batch_confirm
- **WHEN** the user asks "DEMOA2 和 DEMOA4 在 5200、1000的库存分别是多少" (same conversation)
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

#### Scenario: awaiting_batch_confirm clears session last_context
- **WHEN** the orchestrator returns an `awaiting_batch_confirm` outcome
- **THEN** the workbench emits `lastContext=None` for that turn
- **AND** the next turn's intent adapter receives no `last_context`
- **AND** the LLM does not re-emit `multi_parameters` from the prior material on the user's "确认" reply (no dead loop)

#### Scenario: awaiting_batch_confirm serializes combinations to workbench
- **WHEN** the orchestrator returns an `awaiting_batch_confirm` outcome with combinations
- **THEN** the workbench dict includes the `combinations` array and `callPlan`
- **AND** the frontend holds them in `pendingOutcome` pending user confirmation

#### Scenario: continue_batch service entry executes confirmed batch
- **WHEN** the user confirms the batch (frontend button or CLI `--continue-batch`)
- **THEN** the service layer routes a `BatchContinuation` (callPlan + combinations) to `continue_batch`
- **AND** `continue_batch` executes each combination and aggregates results
- **AND** returns the batch narrative to the user

