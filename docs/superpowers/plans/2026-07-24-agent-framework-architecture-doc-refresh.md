# Agent Framework Architecture Documentation Refresh Plan

> **For agentic workers:** Execute inline in the current checkout. Do not create a branch, commit, or modify code, schemas, Registry, configuration, dependencies, or runtime artifacts.

**Goal:** Synchronize the SAP Nexus Agent architecture, technology selection, implementation roadmap, runbooks, framework comparison, and repository overview with the verified OpenHarness/DeerFlow analysis, the current archived S1 state, and the verified gap between the target five-state semantic decision contract and the current single-capability selector runtime.

**Architecture:** Preserve Capability Registry, deterministic planning, Approval Guard, SAP Execution Gateway, Evidence, and Eval Harness as the only execution authorities. Add documentation-only boundaries for trusted identity, three-layer state ownership, durable runtime gates, real event streaming, deterministic composition output, and repository hygiene without starting a runtime implementation.

**Tech Stack:** Markdown, OpenSpec CLI, Git diff validation.

## Global Constraints

- Keep `sap-nexus-planner-dry-run` as the next business change and dry-run only.
- Do not add OpenHarness or DeerFlow as a runtime dependency or execution authority.
- Do not select a durable store, graph database, memory backend, authentication product, or new executor in this documentation change.
- Require trusted identity and durable run/approval state before shared S3, long approval, multi-worker/HA, or non-sandbox WRITE exposure.
- Preserve existing user changes and intentional Wiki archive moves.
- Do not commit.

---

### Task 1: Refresh the three primary architecture documents

**Files:**
- Modify: `docs/wiki/sap-nexus-agent-technical-architecture.md`
- Modify: `docs/wiki/sap-nexus-agent-technology-selection.md`
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`

- [x] Record S1 as implemented, verified, and archived.
- [x] Add trusted principal, tenant, role, data-scope, approval-actor, and separation-of-duty boundaries.
- [x] Formalize `ConversationState`, `PlanExecutionState`, and `EvidenceState` ownership.
- [x] Distinguish current buffered SSE-format output from target durable incremental streaming.
- [x] Define deterministic `OutputProjection` / aggregation and incomplete/freshness semantics for S3.
- [x] Add `P0A` repository hygiene and `P0B` trusted runtime gates while keeping S2 next.
- [x] Keep Memory, Dynamic Planner, graph database, Multi-Agent execution, and Write composition deferred.

### Task 1A: Make semantic decision maturity explicit

**Files:**
- Modify: `docs/wiki/sap-nexus-agent-technical-architecture.md`
- Modify: `docs/wiki/sap-nexus-agent-technology-selection.md`
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
- Modify: `docs/runbooks/08-capability-matching-contract.md`
- Modify: `docs/runbooks/10-capability-composition-contract.md`
- Modify: `docs/runbooks/README.md`

- [x] Record that current `IntentParseResult -> SelectionResult` supports only partial implicit decision behavior and can reduce multi-goal input to the first matching intent.
- [x] Split row 19/S2 into S2-A Semantic MatchDecision Hardening and S2-B Planner Dry-run without creating a second runtime or changing execution authority.
- [x] Keep Phase 3+ `sap-nexus-capability-matching-contract` limited to semantic index, embedding/hybrid retrieval, cross-domain routing and LLM rerank.
- [x] Define `CapabilityCard` as a governed semantic projection that excludes technical binding details.
- [x] Add multi-intent, ambiguity, visibility, capability-gap, prompt-injection and false-`SELECT` Eval gates.
- [x] Correct runbook statements that presented `ESCALATE_TO_PLANNER` as already reliable runtime behavior.

### Task 2: Synchronize operational and comparison documents

**Files:**
- Modify: `docs/runbooks/README.md`
- Modify: `docs/runbooks/10-capability-composition-contract.md`
- Modify: `docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md`

- [x] Replace stale active/archive-pending S1 status with the archived path.
- [x] Update moved Wiki references to `docs/wiki/archive/`.
- [x] Update OpenHarness runtime facts to acknowledge implemented S1 schemas, catalogs, graph, and validation-only boundary.
- [x] Add P0A/P0B gates, real streaming, run ownership, durable approval, and deterministic composition output acceptance criteria.

### Task 3: Correct repository overview drift

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`

- [x] Replace Neo4j-as-current-runtime wording with YAML/JSON Schema plus immutable in-memory graph.
- [x] Remove unsupported Agent FastAPI and ArkCLI authentication claims.
- [x] Label Workbench run/approval state and SSE behavior as local MVP limitations.
- [x] State that authentication/authorization and durable runtime are production gates, not shipped capabilities.

### Task 4: Verify documentation consistency

**Files:**
- Inspect: all modified documentation files.

- [x] Search for stale S1 archive-pending, moved path, Neo4j-runtime, Agent FastAPI, and ArkCLI claims.
- [x] Run `git diff --check` and require exit `0`.
- [x] Run `openspec list --json` and confirm no active changes.
- [x] Run `openspec validate --all --strict` and require all specs to pass.
- [x] Confirm `git status --short` contains only the previously approved documentation work plus this documentation refresh.
