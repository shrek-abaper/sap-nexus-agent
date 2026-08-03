# Conversational Context and Multi-Value Batch Query Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `12-conversational-context-and-multi-value-batch` |
| Version | `v0.1.2` |
| Status | `Completed / Archived` |
| Created | `2026-08-01` |
| Updated | `2026-08-03` |
| Last Change | Current-state correction after P0B: preserves the original pre-P0B feature record while recognizing durable Run/Session, trusted principal, durable approval and incremental SSE as archived foundations. No runtime change. |
| Workstream | Instant multi-turn conversation context (row 19A) + multi-value batch query (row 19B) |
| Related Changes | `sap-nexus-agent-conversational-context` (archived 2026-07-26); `sap-nexus-agent-llm-intent-enhancement` (archived 2026-07-26); `fix-batch-confirm-loop` (archived 2026-07-27); `multi-value-batch-service-integration` (archived 2026-07-27) |
| Current Phase | Closed; do not resume implementation from this runbook |
| Successor | Runbook 13 starts the complete Agent workstream; later runbooks own multi-capability execution |
| Reopen Policy | Do not reopen; WRITE batch semantics require a separate future change |

---

## 1. Session Goal

This archived runbook records two connected capabilities delivered between 2026-07-26 and 2026-07-27:

1. **Instant multi-turn conversation context** (row 19A): close the gap where a stateless single-turn intent parser cannot resume a `CLARIFY` after the user supplies bare parameters in the next turn.
2. **Multi-value batch query** (row 19B): let a single utterance carrying multiple values for one parameter (e.g. several materials) fan out to N atomic executions after explicit user confirmation.

Both were delivered as lightweight, process-local, READ-only v1 features before P0B. P0B has since replaced Run/Session state with durable stores and added trusted principal, durable approval and incremental SSE/reconnect; this historical runbook does not redefine those newer runtime contracts.

The four changes form one chain: `conversational-context` lays the session/state foundation -> `llm-intent-enhancement` adds LLM coreference resolution and multi-value split (but stops at the orchestrator layer) -> `fix-batch-confirm-loop` stops a death loop the second change introduced -> `multi-value-batch-service-integration` wires `continue_batch` through to workbench/CLI/API/SSE so the batch feature is end-to-end usable.

---

## 2. Archive Sources and Verified Baseline

```text
AGENTS.md
docs/runbooks/README.md
docs/runbooks/12-conversational-context-and-multi-value-batch.md
docs/runbooks/08-capability-matching-contract.md (§4.1.1 CLARIFY cross-turn continuation)
docs/wiki/sap-nexus-agent-technical-architecture.md (§4.2.1, §4.2.2, §4.2.3)
docs/wiki/sap-nexus-agent-implementation-roadmap.md (row 19A, 19B)
openspec/specs/conversational-context/spec.md
agent/sap_nexus_agent/conversation_context.py
agent/sap_nexus_agent/llm_intent.py
agent/sap_nexus_agent/intent.py
```

Verified feature baseline and later runtime supersession:

- `PendingClarification` and `ConversationState` are advisory context, never execution authority; once `SELECT` fires a `CallPlan` / `ApprovalRecord`, execution authority stays with the existing state machine.
- The original feature stored session state in the Workbench backend process; P0B later replaced it with durable Run/Session stores. The Python Agent remains a structured runner fed current query plus governed context.
- LLM history re-injection applies the authority/untrusted-data separation contract (static rules as `SystemMessage`; historical text as a hidden `<durable_context_data>` `HumanMessage`).
- `awaiting_batch_confirm` returns combinations without executing any Gateway call; `continue_batch` runs each combination through the existing single-capability `SELECT -> CallPlan -> Gateway validate/execute` path.
- v1 is READ-only: Actions (`sideEffect=sap_write`) fall to `awaiting_approval` and do not enter `continue_batch`.

---

## 3. Staged Scope

### 19A: `sap-nexus-agent-conversational-context` (archived 2026-07-26)

1. `PendingClarification` advisory state in backend `sessions` Map.
2. `IntentAdapter` signature extended to `Callable[[str, ConversationContext | None], IntentParseResult]`; default `None` preserves all single-turn tests.
3. Sticky-CLARIFY cross-turn slot-fill: an utterance with no primary keyword is treated as a slot-fill answer; re-run the extractor, merge parameters, re-evaluate missing.
4. LLM path history re-injection with authority/untrusted-data separation.
5. Frontend `conversationId` generation + “new conversation” button; CLI `--context` stdin JSON mode.

### 19A-derivative: `sap-nexus-agent-llm-intent-enhancement` (archived 2026-07-26)

1. LLM `_messages` includes `last_context` (capability + parameters) for stable coreference (“这个物料” -> prior material).
2. LLM becomes the primary path; rule fallback only on `LlmUnavailable`, inheriting `last_context` material.
3. Multi-value parameter split: `multi_parameters`, `expand_combinations` cartesian product, `awaiting_batch_confirm` outcome (carries combinations, does not execute), `continue_batch` per-combination execution, `narrate_inventory_facts` aggregation, soft cap `BATCH_COMBINATION_CAP=20`.
4. `continue_batch` stops at the orchestrator layer (no service-layer callers); service integration is deferred to the batch-integration change.

### 19B: `sap-nexus-multi-value-batch-query`

#### `fix-batch-confirm-loop` (hotfix, archived 2026-07-27)

1. Fix the `awaiting_batch_confirm` death loop: `_last_context_from_outcome` returned `LastContext(SELECT, {material, unit})`, so after the user confirmed, the LLM picked up the stale material and re-emitted `multi_parameters` indefinitely.
2. Fix: early-return `None` for `awaiting_batch_confirm` (after the `awaiting_approval` early return) to clear session `last_context`. 1-line early return + 1 regression test, TDD RED->GREEN.

#### `multi-value-batch-service-integration` (archived 2026-07-27)

1. Wire the previously-unwired `continue_batch` into the service layer, mirroring `continue_action` approval flow.
2. `workbench_output.py` serializes `combinations` + `callPlan`; frontend `BatchContinuation` type + `pendingOutcome` holds combinations + confirm button; CLI `--continue-batch` flag; API `/api/agent-runs/[runId]/batch` continuation route; SSE `awaiting_batch_confirm` state event.
3. End-to-end: Turn N multi-value -> `awaiting_batch_confirm`; Turn N+1 confirm -> `continue_batch` -> aggregated batch result.

### Still out of scope (v1)

- Cross-turn `ESCALATE_TO_PLANNER` disambiguation and `SHOW_OPTIONS` selection.
- Coexistence of approval-pending with CLARIFY-pending.
- Original v1 excluded cross-restart persistence and multi-worker sharing; P0B later delivered durable Run/Session state. Long-conversation compaction remains separate.
- WRITE batch approval semantics (per-combo approval snapshot / hash / atomic claim).
- Server-side `BatchRecord` audit, combinations pagination/streaming, per-combo `gateway_execute` SSE event.
- `BATCH_COMBINATION_CAP` as a configurable value (currently hardcoded `20`).

---

## 4. Safety Boundaries

- `ConversationState` and `awaiting_batch_confirm` are advisory context, never execution authority; they do not interact with the `CallPlan` / `ApprovalRecord` lifecycle.
- P0B now owns durable Run/Session state. Batch combinations retain their explicit READ-only continuation contract and must not be treated as PlanExecution or WRITE authority.
- LLM history re-injection must apply the authority/untrusted-data separation contract; the rule path does not call the LLM and is unaffected.
- `awaiting_batch_confirm` must return combinations without executing; explicit user confirmation is required before `continue_batch`.
- v1 is READ-only: Actions fall to `awaiting_approval` and do not enter `continue_batch`; WRITE batch approval semantics are a separate future design.
- `BATCH_COMBINATION_CAP=20` soft cap prevents cartesian-product explosion; over-cap is rejected.
- Each combination still goes through the existing single-capability `SELECT -> CallPlan -> Gateway validate/execute` path; no second execution authority is introduced.

---

## 5. Archived Acceptance Criteria

| Area | Acceptance | Evidence |
|---|---|---|
| Sticky-CLARIFY | Turn 1 CLARIFY -> turn 2 bare parameters resolves to SELECT | e2e verified; pytest 426 passed/1 skipped/1 pre-existing |
| ConversationContext | `IntentAdapter` accepts `ConversationContext | None`; default `None` preserves single-turn tests | conversational-context verify |
| History re-injection | LLM path applies authority/untrusted-data separation | conversational-context verify |
| Multi-value split | `multi_parameters` -> `expand_combinations` -> `awaiting_batch_confirm` (no execute) | llm-intent-enhancement 12/12 scenarios |
| Batch end-to-end | Turn N awaiting_batch_confirm -> Turn N+1 confirm -> continue_batch -> aggregated result | batch-integration 7/7 scenarios |
| READ-only | Actions fall to `awaiting_approval`, not `continue_batch` | design doc + tests |
| Death loop fix | `awaiting_batch_confirm` clears `last_context`; no infinite loop | fix-batch-confirm-loop regression test |
| OpenSpec | All specs valid | openspec validate --all --strict 11 passed |

### Verification records

- `conversational-context`: `docs/superpowers/reports/2026-07-26-sap-nexus-agent-conversational-context-verify.md`; openspec 11 passed/0 failed; verify-script 11 passed/0 failed; pytest 426 passed/1 skipped/1 pre-existing failed (cwd-relative, present on base-ref, unrelated); npm frontend verify green; e2e turn1 CLARIFY -> turn2 sticky SELECT.
- `llm-intent-enhancement`: `docs/superpowers/reports/2026-07-26-sap-nexus-agent-llm-intent-enhancement-verify.md`; openspec 12 passed/0 failed; tasks 24/24; plan 12/12; 12/12 scenarios; 2/2 requirements.
- `fix-batch-confirm-loop`: `docs/superpowers/reports/2026-07-27-fix-batch-confirm-loop-verify.md`; openspec 12 passed/0 failed; tasks 6/6; pytest 438 passed/1 skipped (no regression).
- `multi-value-batch-service-integration`: `docs/superpowers/reports/2026-07-27-multi-value-batch-service-integration-verify.md`; openspec 12 passed/0 failed; pytest 442 passed/1 skipped; tasks 19/19; 7/7 scenarios; npm frontend verify exit 0; verify-script exit 0.

---

## 6. Archive Handoff - Do Not Reopen

1. Re-read technical-architecture §4.2.1 / §4.2.2 / §4.2.3, this runbook, and runbook 08 §4.1.1.
2. Check `git status --short` and `openspec list --json`; no active change is assumed.
3. All four changes are archived; the multi-value batch query capability is end-to-end usable (READ-only v1).
4. P0B is complete. Continue from runbook 13, then follow runbooks 14-22; do not skip directly to PlanExecutor or WRITE.
5. WRITE batch approval remains separate future scope and must not reuse the READ batch path.
6. Non-blocking engineering cleanup surfaced as verify SUGGESTIONs (low-risk tweak candidates): `_requires_safe_fallback` dead-code removal, `multiParameters` non-dict guard, `continue_batch` error-handling hardening (first-error-only on full failure, silent None-fact drop), PO descriptor `requiredOneOf`, per-combo `gateway_execute` SSE event, `BATCH_COMBINATION_CAP` as config.

---

## Session Closeout - 2026-08-01

### Completed

- Documentation-governance pass: retroactively registered four already-archived changes (conversational-context, llm-intent-enhancement, fix-batch-confirm-loop, multi-value-batch-service-integration) into roadmap row 19A/19B, runbook README, this new runbook 12, technical-architecture §4.2.3, and runbook 08 §4.1.1 cross-reference.
- No runtime change in this pass; docs only.

### Verified

- Command: `openspec validate --all --strict`
- Result: 11 passed, 0 failed (confirmed at this pass’s verification step; 11 specs, no active change).
- Command: `git diff --name-only`
- Result: only `docs/` paths (confirmed at this pass’s verification step).

### Blockers

- None.

### Historical Handoff - Superseded

> Superseded by completed P0B foundations and runbooks 13-22. Retained only as the `2026-08-01` closeout record.

1. P0B durable runtime OR S3 read-composition pilot OR WRITE batch approval semantics - user decision.
2. Optional low-risk cleanup tweak from verify SUGGESTIONs.
