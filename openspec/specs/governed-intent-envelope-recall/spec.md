# governed-intent-envelope-recall Specification

## Purpose
TBD - created by syncing change sap-nexus-governed-intent-capability-recall. Update Purpose after archive.
## Requirements
### Requirement: Versioned IntentEnvelope data structure

The system SHALL replace the flat `IntentParseResult` with a versioned `IntentEnvelope` as the LLM-first intent carrier. `IntentEnvelope` SHALL carry `envelope_id` (UUID for replay), `utterance`, `goals` (tuple of `IntentGoal`), `user_constraints`, `ambiguities`, `reference_turn_id`, `model_evidence`, `snapshot_id` (from `GovernedContext`), `discard_reasons`, and `created_by` (`"llm"` or `"rule"`). Each `IntentGoal` SHALL carry `goal_text`, `capability_hint` (advisory), `parameters` (advisory), and `missing` (advisory). `IntentEnvelope` SHALL be immutable (frozen dataclass). `IntentParseResult` SHALL be removed (BREAKING).

#### Scenario: LLM path produces IntentEnvelope with snapshot_id
- **WHEN** the LLM intent path parses an utterance under a `GovernedContext` with `snapshot_id="snap-001"`
- **THEN** the returned `IntentEnvelope.snapshot_id="snap-001"` and `created_by="llm"`
- **AND** `envelope_id` is a non-empty UUID
- **AND** `goals` contains at least one `IntentGoal` derived from the LLM payload

#### Scenario: Rule fallback produces IntentEnvelope
- **WHEN** the LLM is unavailable (`LlmUnavailable`) and the rule fallback path runs
- **THEN** the returned `IntentEnvelope.created_by="rule"`
- **AND** `model_evidence` is empty
- **AND** `goals` are derived from rule-based keyword matching
- **AND** `snapshot_id` is still bound to the current `GovernedContext`

#### Scenario: IntentParseResult removed
- **WHEN** any caller previously consumed `IntentParseResult`
- **THEN** the type is no longer importable and the caller MUST consume `IntentEnvelope` instead

### Requirement: Closed-set recall stage

The system SHALL apply a closed-set recall stage before the deterministic matcher, taking `VisibleCapabilitySet` + utterance as input and producing `recall_candidates` (advisory). The recall SHALL merge three independent sources: lexical recall (keyword match against capability name/description), alias recall (capability aliases from registry), and example recall (capability examples from registry). The recall SHALL dedupe candidates by `capability_id`. The recall SHALL NOT produce a `MatchDecision` (advisory only). The recall SHALL NOT use embedding, vector store, or RAG.

#### Scenario: Lexical recall matches capability name
- **WHEN** the utterance contains "库存" and `VisibleCapabilitySet` contains `MM.Inventory.GetAvailability` with "库存" in its name/description
- **THEN** `MM.Inventory.GetAvailability` is included in `recall_candidates`

#### Scenario: Alias recall matches capability alias
- **WHEN** the utterance contains "PO" and `VisibleCapabilitySet` contains `MM.PurchaseOrder.GetList` with alias "PO"
- **THEN** `MM.PurchaseOrder.GetList` is included in `recall_candidates`

#### Scenario: Example recall matches capability example
- **WHEN** the utterance resembles a registered example for `MM.PR.CreateDraft`
- **THEN** `MM.PR.CreateDraft` is included in `recall_candidates`

#### Scenario: Unknown capability is not recalled
- **WHEN** the utterance mentions "Foo.Bar" which is not in `VisibleCapabilitySet`
- **THEN** `Foo.Bar` is NOT included in `recall_candidates`
- **AND** the LLM candidate `capability_hint="Foo.Bar"` is recorded in `discard_reasons`

### Requirement: Registry aliases and examples fields

The system SHALL extend the capability registry schema with optional `aliases` (list of strings) and `examples` (list of strings) fields per capability. These fields SHALL be the data source for alias recall and example recall respectively. The fields SHALL be optional; when absent, the corresponding recall source returns empty for that capability. The `CapabilityDescriptor` loaded by `registry_loader.py` SHALL expose `aliases` and `examples` as tuple fields. Existing capabilities without these fields SHALL continue to load successfully (backward compatible).

#### Scenario: Capability with aliases and examples
- **WHEN** `MM.Inventory.GetAvailability` has `aliases: ["库存查询", "物料可用量"]` and `examples: ["查物料 DEMOA2 在 1000 工厂的库存"]`
- **THEN** `CapabilityDescriptor.aliases=("库存查询", "物料可用量")` and `CapabilityDescriptor.examples=("查物料 DEMOA2 在 1000 工厂的库存",)`

#### Scenario: Capability without aliases and examples
- **WHEN** a capability does not have `aliases` or `examples` fields in the registry
- **THEN** `CapabilityDescriptor.aliases=()` and `CapabilityDescriptor.examples=()`
- **AND** the capability still loads successfully

#### Scenario: Alias recall uses registry aliases
- **WHEN** the utterance contains "库存查询" and `MM.Inventory.GetAvailability` has alias "库存查询"
- **THEN** `MM.Inventory.GetAvailability` is included in `recall_candidates` via alias recall

### Requirement: Bounded rerank stage

The system SHALL apply a bounded rerank stage after recall, scoring `recall_candidates` by heuristic (no embedding): LLM `capability_hint` match (+3), lexical match (+2), alias match (+2), example match (+1), parameter fit (required parameters satisfied, +1). Parameter fit SHALL be determined by checking whether the LLM-provided parameters in `IntentGoal.parameters` cover all required inputs of the candidate capability (consistent with the selector's `missing` computation); if all required inputs are covered, +1, otherwise +0. The rerank SHALL output `ranked_candidates` (sorted desc by score) and `rerank_evidence` (per-candidate score breakdown). The rerank SHALL NOT produce a `MatchDecision` (advisory only).

#### Scenario: LLM hint ranks first
- **WHEN** LLM `capability_hint="MM.Inventory.GetAvailability"` and recall includes `MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList`
- **THEN** `MM.Inventory.GetAvailability` has score >= 5 (hint + lexical + param fit) and ranks first in `ranked_candidates`
- **AND** `rerank_evidence` contains the score breakdown for each candidate

#### Scenario: Tie-break is stable
- **WHEN** two candidates have the same rerank score
- **THEN** the tie is broken by `capability_id` alphabetical order (stable, deterministic)

#### Scenario: Parameter fit only when all required inputs covered
- **WHEN** LLM provides parameters `{"material": "DEMOA2"}` for `MM.Inventory.GetAvailability` (required: material + plant)
- **THEN** parameter fit is +0 (plant missing), so the candidate does NOT get the +1 bonus
- **AND** when LLM provides `{"material": "DEMOA2", "plant": "1000"}`, parameter fit is +1

### Requirement: LLM output discard with structured reasons

The system SHALL discard LLM output fields that contain unknown capabilities, technical fields (e.g. `baseUrl`, `rfcName`, `credential`), or invalid parameters, and SHALL record each discarded field in `IntentEnvelope.discard_reasons` with a structured reason string (e.g. `"unknown_capability:Foo.Bar"`, `"technical_field:baseUrl"`, `"invalid_param:__proto__"`). The system SHALL NOT silently drop LLM output. `discard_reasons` SHALL be empty when the LLM output is fully valid.

#### Scenario: Unknown capability discarded with reason
- **WHEN** the LLM payload contains `capability_hint="Foo.Bar"` not in `VisibleCapabilitySet`
- **THEN** the hint is NOT included in `goals`
- **AND** `discard_reasons` contains `"unknown_capability:Foo.Bar"`

#### Scenario: Technical field discarded with reason
- **WHEN** the LLM payload contains a parameter `baseUrl="http://..."`
- **THEN** the parameter is NOT included in `goals[0].parameters`
- **AND** `discard_reasons` contains `"technical_field:baseUrl"`

#### Scenario: Valid LLM output has empty discard_reasons
- **WHEN** the LLM payload contains only known capabilities and valid parameters
- **THEN** `discard_reasons` is empty

### Requirement: Decision replay contract

The system SHALL ensure every `MatchDecision` is replayable by carrying `envelope_id`, `recall_candidates`, `rerank_evidence`, and `discard_reasons` fields on `MatchDecision` (or a reference to the `IntentEnvelope`). A reviewer SHALL be able to trace any decision back to: the original `IntentEnvelope`, the recall candidates, the rerank evidence, the filter reasons, and the `snapshot_id`.

#### Scenario: SELECT decision carries replay fields
- **WHEN** `MatchDecision.decision_type=SELECT` for `MM.Inventory.GetAvailability`
- **THEN** `MatchDecision.envelope_id` matches the `IntentEnvelope` that produced the decision
- **AND** `MatchDecision.recall_candidates` and `MatchDecision.rerank_evidence` are non-empty
- **AND** `MatchDecision.discard_reasons` is present (possibly empty)

#### Scenario: REJECT decision carries discard reasons
- **WHEN** `MatchDecision.decision_type=REJECT` due to unknown capability
- **THEN** `MatchDecision.discard_reasons` contains the structured reason for the discarded LLM candidate

### Requirement: Cross-turn SHOW_OPTIONS continuation

The system SHALL support cross-turn SHOW_OPTIONS continuation via `ConversationContext.pending_show_options` (advisory, no execution authority). When turn N produces `SHOW_OPTIONS`, the system SHALL write `PendingShowOptions(candidates, snapshot_id)` to `ConversationContext`. When turn N+1 selects one of the candidates, the system SHALL clear `pending_show_options` and proceed to `SELECT` for the selected capability. The `pending_show_options` state SHALL be advisory only and MUST NOT influence `CallPlan` / `ApprovalRecord` lifecycle.

#### Scenario: Turn N SHOW_OPTIONS writes pending state
- **WHEN** turn N "订单" produces `SHOW_OPTIONS` with candidates `[MM.PurchaseOrder.GetList, MM.PR.CreateDraft]`
- **THEN** `ConversationContext.pending_show_options` is set with the two candidates and the current `snapshot_id`

#### Scenario: Turn N+1 selection clears pending and reaches SELECT
- **WHEN** turn N+1 "采购订单" selects `MM.PurchaseOrder.GetList` from the pending options
- **THEN** `ConversationContext.pending_show_options` is cleared
- **AND** the system proceeds to `SELECT` for `MM.PurchaseOrder.GetList`

#### Scenario: Turn N+1 new intent discards pending SHOW_OPTIONS
- **WHEN** turn N+1 contains a primary keyword for a different capability
- **THEN** `ConversationContext.pending_show_options` is cleared
- **AND** the new turn is processed as a fresh intent

### Requirement: Cross-turn ESCALATE_TO_PLANNER continuation

The system SHALL support cross-turn ESCALATE_TO_PLANNER continuation via `ConversationContext.pending_escalate` (advisory, no execution authority). When turn N produces `ESCALATE_TO_PLANNER`, the system SHALL write `PendingEscalate(handoff, snapshot_id)` to `ConversationContext`. When turn N+1 confirms continuation, the system SHALL clear `pending_escalate` and hand off to the planner (dry-run only, no Gateway execution). The `pending_escalate` state SHALL be advisory only and MUST NOT influence `CallPlan` / `ApprovalRecord` lifecycle.

#### Scenario: Turn N ESCALATE writes pending state
- **WHEN** turn N "库存 + 采购订单供给概览" produces `ESCALATE_TO_PLANNER` with `handoff`
- **THEN** `ConversationContext.pending_escalate` is set with the `handoff` and the current `snapshot_id`

#### Scenario: Turn N+1 confirm clears pending and hands off to planner
- **WHEN** turn N+1 "继续" confirms the escalation
- **THEN** `ConversationContext.pending_escalate` is cleared
- **AND** the system hands off to the planner (dry-run only, no Gateway execution)

#### Scenario: Turn N+1 new intent discards pending ESCALATE
- **WHEN** turn N+1 contains a new primary keyword unrelated to the pending escalation
- **THEN** `ConversationContext.pending_escalate` is cleared
- **AND** the new turn is processed as a fresh intent

### Requirement: Mutual exclusivity of pending states

The system SHALL ensure at most one of `PendingClarification`, `PendingShowOptions`, `PendingEscalate` is set in `ConversationContext` at any time. Writing a new pending state SHALL clear any existing pending state.

#### Scenario: SHOW_OPTIONS clears pending CLARIFY
- **WHEN** `ConversationContext.pending_clarification` is set and turn N+1 produces `SHOW_OPTIONS`
- **THEN** `pending_clarification` is cleared before `pending_show_options` is set

#### Scenario: CLARIFY clears pending SHOW_OPTIONS
- **WHEN** `ConversationContext.pending_show_options` is set and turn N+1 produces `CLARIFY`
- **THEN** `pending_show_options` is cleared before `pending_clarification` is set
