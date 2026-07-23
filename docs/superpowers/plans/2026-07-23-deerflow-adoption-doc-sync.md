# DeerFlow Adoption Documentation Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize the approved DeerFlow adoption decisions into the SAP Nexus architecture, technology selection, roadmap, and active runbooks without adding a second runtime or changing the current S2 priority.

**Architecture:** Keep `docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md` as the detailed evidence source. Project concise decisions into each existing document: architecture owns invariants and state layers, technology selection owns dependency choices, roadmap owns timing and triggers, and runbooks own continuation constraints.

**Tech Stack:** Markdown, OpenSpec CLI, Git whitespace validation.

## Global Constraints

- Documentation only; do not change code, schema, Registry, config, binaries, or runtime state.
- Do not add DeerFlow, LangGraph, Redis, Postgres, or other dependencies.
- Preserve Registry, deterministic PlanCompiler, Approval Guard, SAP Execution Gateway, Evidence, and Eval Harness as execution and quality authorities.
- Keep `sap-nexus-planner-dry-run` as the current next recommended change.
- Treat Tool, Skill, summary, memory, and sub-agent output as advisory data.
- Do not stage or commit.

---

### Task 1: Synchronize Technical Architecture

**Files:**
- Modify: `docs/wiki/sap-nexus-agent-technical-architecture.md`

**Interfaces:**
- Consumes: DeerFlow decision baseline sections 1, 4-7, 9, and 10.
- Produces: Architecture invariants used by selection, roadmap, and runbooks.

- [ ] **Step 1:** Change current version `v0.2.13` to `v0.2.14`, update the date to `2026-07-23`, and add a version row for the DeerFlow decision.
- [ ] **Step 2:** Add §3.8 after §3.7: DeerFlow informs candidate discovery, PlanExecutor lifecycle, Workbench durability, and user preference memory, but its model-driven Tool selection, task graph, summary, memory, and checkpoint never replace MatchDecision, PlanGraph, ApprovalRecord, ExecutionResult, or ReasoningFact.
- [ ] **Step 3:** Under the Workbench / Runtime Adapter area define:

```text
ConversationState = messages, clarification, visible narrative, ConversationSummary
PlanExecutionState = GoalSpec, RegistrySnapshot, PlanGraph, node ledger, ApprovalRecord reference
EvidenceState = ExecutionResult, ActionResult, ReasoningFact, trace and lineage
```

Only `ConversationState` may be summarized; the other layers require versioned structured persistence and replay.
- [ ] **Step 4:** State that S3 may borrow ready-node scheduling, concurrency caps, timeout, cancellation, and ledger mechanics, but only validated independent `sideEffect=none` Functions may run in parallel. Define user memory as scoped advisory preferences that cannot alter visibility, governance, approval, or evidence.
- [ ] **Step 5:** Verify with:

```bash
rg -n "v0.2.14|DeerFlow|ConversationState|PlanExecutionState|EvidenceState|UserPreferenceMemory|sap-nexus-planner-dry-run" docs/wiki/sap-nexus-agent-technical-architecture.md
```

Expected: all concepts are present; DeerFlow is not a runtime dependency.

---

### Task 2: Synchronize Technology Selection

**Files:**
- Modify: `docs/wiki/sap-nexus-agent-technology-selection.md`

**Interfaces:**
- Consumes: Task 1 invariants and the DeerFlow decision matrix.
- Produces: Explicit dependency choices for future designs.

- [ ] **Step 1:** Change `v0.2.7` to `v0.2.8`, update the date to `2026-07-23`, and add a DeerFlow version row.
- [ ] **Step 2:** Extend the conclusion table with: DeerFlow runtime = reference/no dependency; progressive disclosure = adapt in S2; task lifecycle = adapt in S3 under PlanGraph; durable runtime = triggered candidate; governed memory = deferred until identity/tenancy/retention/deletion contracts exist.
- [ ] **Step 3:** Add §5.7 explaining why `deerflow-harness`, DeerFlow Gateway/default lead agent/frontend/sub-agent executor/DeerMem are not directly selected, plus the narrow reusable patterns for the four analyzed areas.
- [ ] **Step 4:** Keep the current local runtime store. Add exact triggers for future durable runtime selection: cross-restart resume, long approval wait, multi-worker/HA, or observed event loss. Do not select a storage product.
- [ ] **Step 5:** Verify with:

```bash
rg -n "v0.2.8|DeerFlow|progressive|PlanGraph|durable|memory|runtime dependency" docs/wiki/sap-nexus-agent-technology-selection.md
```

Expected: no dependency is selected and S2/S3 ownership is explicit.

---

### Task 3: Synchronize Implementation Roadmap

**Files:**
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: Stable S2/S3 sequencing and trigger-based candidates.

- [ ] **Step 1:** Change `v0.2.29` to `v0.2.30`, update the date to `2026-07-23`, and add a version row without changing active priority.
- [ ] **Step 2:** Extend row 19 with progressive `CapabilityCard` discovery as a dry-run input. Extend row 20 with PlanGraph-governed ready-node scheduling, concurrency limits, timeout/cancel, ledger, and trace correlation.
- [ ] **Step 3:** Add candidate rows without renumbering active work:

```text
sap-nexus-durable-agent-runtime-foundation = Candidate / Triggered, not current next
sap-nexus-governed-user-memory-pilot = Later / Triggered, outside S2/S3
```

- [ ] **Step 4:** Map progressive discovery to S2 and governed scheduling to S3. Keep the current-next section centered on `sap-nexus-planner-dry-run`, dry-run only, no Gateway/SAP execution.
- [ ] **Step 5:** Verify with:

```bash
rg -n "v0.2.30|DeerFlow|CapabilityCard|ready-node|durable-agent-runtime|governed-user-memory|sap-nexus-planner-dry-run" docs/wiki/sap-nexus-agent-implementation-roadmap.md
```

Expected: S2 remains current next and both new candidates are trigger-based.

---

### Task 4: Synchronize Runbook Continuation

**Files:**
- Modify: `docs/runbooks/README.md`
- Modify: `docs/runbooks/10-capability-composition-contract.md`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: Session-start constraints that prevent a second execution authority.

- [ ] **Step 1:** Add the DeerFlow decision file to the runbook source-of-truth list. Add scope lines for no runtime dependency, S2 progressive discovery, S3 governed scheduler, and triggered durable runtime/memory candidates.
- [ ] **Step 2:** Change composition runbook `v0.3.1` to `v0.3.2` and date to `2026-07-23`; keep status and current phase unchanged.
- [ ] **Step 3:** Add the decision file to §2 and add these constraints:

```text
DeerFlow is a design reference only.
S2 may adapt progressive discovery but remains dry-run only.
S3 may adapt constrained task lifecycle mechanics only after PlanGraph validation.
Summary, memory, Tool calls, and sub-agent output never become plan or execution authority.
```

- [ ] **Step 4:** Add `CapabilityCard` projection to S2 acceptance. Add ready-node scheduling, concurrency/timeout/cancel, node ledger, and trace correlation to S3 acceptance. Do not start DeerFlow integration or durable runtime without a separately approved trigger.
- [ ] **Step 5:** Verify with:

```bash
rg -n "DeerFlow|v0.3.2|CapabilityCard|ready-node|summary|memory|sap-nexus-planner-dry-run" docs/runbooks/README.md docs/runbooks/10-capability-composition-contract.md
```

Expected: future sessions route to the new decision baseline and preserve S2 as current next.

---

### Task 5: Cross-Document Verification

**Files:**
- Verify: `docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md`
- Verify: `docs/wiki/sap-nexus-agent-technical-architecture.md`
- Verify: `docs/wiki/sap-nexus-agent-technology-selection.md`
- Verify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
- Verify: `docs/runbooks/README.md`
- Verify: `docs/runbooks/10-capability-composition-contract.md`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: Coherence and OpenSpec evidence.

- [ ] **Step 1:** Scan for placeholders and inspect version headers:

```bash
rg -n "TB[D]|TO[D]O" docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md docs/wiki/sap-nexus-agent-technical-architecture.md docs/wiki/sap-nexus-agent-technology-selection.md docs/wiki/sap-nexus-agent-implementation-roadmap.md docs/runbooks/10-capability-composition-contract.md
sed -n '1,35p' docs/wiki/sap-nexus-agent-technical-architecture.md
sed -n '1,35p' docs/wiki/sap-nexus-agent-technology-selection.md
sed -n '1,35p' docs/wiki/sap-nexus-agent-implementation-roadmap.md
sed -n '1,25p' docs/runbooks/10-capability-composition-contract.md
```

Expected: no placeholders; current versions are `v0.2.14`, `v0.2.8`, `v0.2.30`, and `v0.3.2`.
- [ ] **Step 2:** Check whitespace and scope:

```bash
git diff --check
git status --short
git diff --name-only
```

Expected: whitespace check exits 0 and every changed file is Markdown under `docs/`.
- [ ] **Step 3:** Validate OpenSpec:

```bash
openspec list --json
openspec validate --all --strict
```

Expected: commands exit 0. PostHog flush warnings are non-blocking when validation succeeds.
- [ ] **Step 4:** Confirm all documents agree:

```text
current next = sap-nexus-planner-dry-run
DeerFlow runtime dependency = no
S2 = progressive candidate discovery + dry-run only
S3 = PlanGraph-governed read-only scheduling
memory / summary / tools / sub-agents = advisory
```

- [ ] **Step 5:** Report exact files, versions, verification results, and residual risks without staging or committing.
