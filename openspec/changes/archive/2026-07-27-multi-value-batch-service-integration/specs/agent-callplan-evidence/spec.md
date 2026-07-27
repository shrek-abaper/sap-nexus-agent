## MODIFIED Requirements

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
