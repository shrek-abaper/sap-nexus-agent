# SAP Nexus End-to-End Agent Eval Release Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the archived Agent components into one governed production composition coordinator and prove L1/L2/L3 maturity with an offline hard-gated release report.

**Architecture:** Keep the Python Agent as the semantic front door and PlanGraph v2 author. A thin TypeScript coordinator validates the handoff, reuses the existing PlanExecutor/projection/recommendation/narrative/event/action-governance components, and persists the resulting evidence through the existing durable run store. A separate pure release evaluator consumes real coordinator evidence plus recorded fixtures and emits the highest continuous passing level.

**Tech Stack:** Python 3.12/pytest, TypeScript 5.8, Next.js 15 server runtime, Vitest 3, existing JSONL durable stores, existing Java Gateway HTTP API.

## Global Constraints

- Gateway receives registered `capabilityId` only; no request/model RFC, binding, URL, SQL, credential, or invisible capability.
- All composition artifacts share one non-empty run, trace, snapshot, and trusted principal.
- READ never commits or rolls back; WRITE never executes without recorded exact-subject Human Approval.
- `visibilityLeakageRate=0`, `writeApprovalBypassRate=0`, unsupported narrative claim rate `0`, and fact lineage completeness `100%` are non-compensable hard gates.
- Offline verification performs no live LLM or SAP call; live smoke remains separately authorized and `not_run` in this change.
- Work on the current branch; do not commit unless the user explicitly requests it.

---

### Task 1: Composition handoff and server READ Gateway

**Files:**
- Create: `frontend/src/runtime/composition/types.ts`
- Create: `frontend/src/runtime/composition/handoff.ts`
- Create: `frontend/src/runtime/composition/handoff.test.ts`
- Create: `frontend/src/runtime/composition/server-read-gateway.ts`
- Create: `frontend/src/runtime/composition/server-read-gateway.test.ts`

**Interfaces:**
- Consumes: `WorkbenchOutcome`, `PlanGraphV2`, `GatewayClient`, and server-owned `TrustedPrincipal`.
- Produces: `parseCompositionHandoff(outcome): CompositionHandoff | null` and `createServerReadGateway(options?): GatewayClient`.

- [ ] **Step 1: Write failing handoff tests**

```ts
expect(parseCompositionHandoff(validEscalation)).toMatchObject({
  snapshotId: "snapshot-1",
  graph: { planGraphVersion: 2 },
});
expect(() => parseCompositionHandoff(crossSnapshot)).toThrowError(
  expect.objectContaining({ errorType: "COMPOSITION_SNAPSHOT_MISMATCH" }),
);
```

- [ ] **Step 2: Verify RED**

Run: `npm --prefix frontend test -- src/runtime/composition/handoff.test.ts`
Expected: FAIL because the composition handoff module does not exist.

- [ ] **Step 3: Implement the minimal closed handoff parser**

```ts
export function parseCompositionHandoff(outcome: WorkbenchOutcome): CompositionHandoff | null;
```

Accept only `ESCALATE_TO_PLANNER`, a parseable PlanGraph v2, no gaps, matching non-empty snapshot, and no technical keys. Return `null` for non-composition decisions; throw a typed fail-closed error for an unsafe escalation.

- [ ] **Step 4: Write and run server Gateway adapter tests**

Assert `/capabilities/{capabilityId}/validate` and `/execute` receive only `{parameters}`, map Gateway response fields to `GatewayClient`, and reject non-JSON/error responses without leaking bodies.

Run: `npm --prefix frontend test -- src/runtime/composition/handoff.test.ts src/runtime/composition/server-read-gateway.test.ts`
Expected: PASS.

---

### Task 2: Production multi-READ composition coordinator

**Files:**
- Create: `frontend/src/runtime/composition/coordinator.ts`
- Create: `frontend/src/runtime/composition/evidence.ts`
- Create: `frontend/src/runtime/composition/coordinator.test.ts`

**Interfaces:**
- Consumes: `CompositionHandoff`, `DurableRunStore`, `GatewayClient`, `DecisionConstraints`, clock/worker dependencies.
- Produces: `CompositionCoordinator.execute(input): Promise<CompositionOutcome>` containing executor result, facts, projection, recommendation, narrative, evidence events, and optional `ActionGovernanceInput`.

- [ ] **Step 1: Write the failing complete L2 test**

```ts
const outcome = await coordinator.execute(validDualReadInput);
expect(outcome.projection.completeness).toBe("complete");
expect(outcome.narrative.claims.every((claim) => claim.evidenceRefs.length > 0)).toBe(true);
expect(outcome.events.map((event) => event.sequence)).toEqual(
  [...outcome.events].map((_, index) => index + 2),
);
```

- [ ] **Step 2: Verify RED**

Run: `npm --prefix frontend test -- src/runtime/composition/coordinator.test.ts`
Expected: FAIL because `CompositionCoordinator` does not exist.

- [ ] **Step 3: Implement the minimal L2 pipeline**

```ts
PlanExecutor.execute(graph, runId, snapshotId)
  -> ProjectionInputAssembler.assemble(result, factBuilders)
  -> outputRegistry.resolve("material-supply-snapshot", "1.0.0").project(input)
  -> RecommendationDecisionEngine.decide(request)
  -> createNarrativeEnvelope(sourceInput)
  -> projectPlanEvidenceEvents(bundle);
```

Register the exact `material-shortage-pr@1.0.0` RuleSet against the run snapshot. Derive decision constraints only from server-validated action-node bindings; missing inputs remain insufficient.

- [ ] **Step 4: Add partial/failure tests before behavior**

Cover timeout/cancel, missing fact builder, stale projection, unsupported narrative output, unknown refs, and cross-snapshot objects. Assert incomplete/partial state and zero Action preparation.

- [ ] **Step 5: Implement evidence alias objects and partial semantics**

Every NarrativeEnvelope evidence ref must resolve to a same-snapshot `PlanEvidenceObject`. Do not rewrite model claims or invent evidence; fallback to the deterministic narrative when validation fails.

- [ ] **Step 6: Verify Task 2**

Run: `npm --prefix frontend test -- src/runtime/composition/coordinator.test.ts src/runtime/plan-executor/plan-executor.test.ts src/runtime/projection src/runtime/recommendation src/runtime/narrative`
Expected: PASS.

---

### Task 3: Workbench runtime and plan-aware Action integration

**Files:**
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/src/runtime/durable/types.ts`
- Modify: `frontend/src/runtime/agent-runtime-adapter.test.ts`
- Test: `frontend/src/runtime/action-governance/plan-action-runtime.test.ts`

**Interfaces:**
- Consumes: Python `WorkbenchOutcome.dryRun`, `CompositionCoordinator`, existing global durable stores, and `PlanActionContinuation`.
- Produces: durable L2/L3 event chains through `createAgentRun`; L3 returns an existing plan-aware pending approval and uses existing approval routes for continuation.

- [ ] **Step 1: Write a failing adapter L2 test**

Inject a Python runner returning a valid ESCALATE handoff and inject a fake coordinator/Gateway. Poll the run events and assert `plan_compiled` through `narrative_completed` plus `run_completed` are durable.

- [ ] **Step 2: Verify RED**

Run: `npm --prefix frontend test -- src/runtime/agent-runtime-adapter.test.ts`
Expected: FAIL because the adapter currently emits only a dry-run MatchDecision.

- [ ] **Step 3: Wire composition without changing L1 paths**

Branch only when `parseCompositionHandoff` returns a handoff. Keep existing `emitEventsFromOutcome` unchanged for SELECT/CLARIFY/SHOW_OPTIONS/REJECT and legacy approval/batch flows.

- [ ] **Step 4: Write a failing pending-approval and replay test**

Assert one proposal creates one durable `PlanApprovalRecord`, WRITE execute remains zero before decision, duplicate event reads are side-effect free, and an exact approved fake/sandbox continuation executes once.

- [ ] **Step 5: Reuse `PlanActionContinuation.prepare` and existing approval routes**

Do not create a second approval store or token. Feed the coordinator's exact `ActionGovernanceInput` into the existing runtime and preserve cross-principal/hash/snapshot checks.

- [ ] **Step 6: Verify Task 3**

Run: `npm --prefix frontend test -- src/runtime/agent-runtime-adapter.test.ts src/runtime/action-governance frontend/tests/runtime`
Expected: PASS.

---

### Task 4: Pure release profiles, metrics, and hard-gate evaluator

**Files:**
- Create: `frontend/src/runtime/release-gate/types.ts`
- Create: `frontend/src/runtime/release-gate/profiles.ts`
- Create: `frontend/src/runtime/release-gate/evaluator.ts`
- Create: `frontend/src/runtime/release-gate/evaluator.test.ts`

**Interfaces:**
- Consumes: normalized `ReleaseCaseResult[]` with level, stage, evidence refs, metrics, execution counts, and fixture metadata.
- Produces: `evaluateRelease(results, target): ReleaseReport` and decisions `NO_RELEASE | L1_ONLY | L2_READ_COMPOSITION | L3_ACTION_GOVERNED`.

- [ ] **Step 1: Write failing continuous-level tests**

```ts
expect(evaluateRelease([...passingL1, ...passingL2, failingL3], "L3").decision)
  .toBe("L2_READ_COMPOSITION");
expect(evaluateRelease([failingL1, ...passingL2], "L3").decision)
  .toBe("NO_RELEASE");
```

- [ ] **Step 2: Write failing non-compensable hard-gate tests**

Assert one visibility leak, approval bypass, unsupported claim, or missing lineage fails the affected level even when all other cases pass. Missing/skipped/stale evidence is never counted as pass.

- [ ] **Step 3: Verify RED, then implement minimal evaluator**

Run: `npm --prefix frontend test -- src/runtime/release-gate/evaluator.test.ts`
Expected before implementation: FAIL; after implementation: PASS.

- [ ] **Step 4: Add report redaction and live-smoke status tests**

Require schema/profile/code/snapshot/fixture versions, totals, denominator, failures, metrics, hard gates, evidence refs, decision, and `liveSmoke.status="not_run"`. Reject credential/raw payload/technical binding keys.

---

### Task 5: Offline fixtures, real scenarios, report runner, and CLI

**Files:**
- Create: `evals/end_to_end_agent_release_profiles.json`
- Create: `evals/end_to_end_agent_release_cases.json`
- Create: `evals/recorded_llm/end_to_end_agent_release.json`
- Create: `frontend/src/runtime/release-gate/scenario-runner.ts`
- Create: `frontend/src/runtime/release-gate/scenario-runner.test.ts`
- Create: `frontend/src/runtime/release-gate/cli.ts`
- Modify: `frontend/package.json`
- Modify: `.gitignore` only if `runtime/evals/results/` is not already ignored.

**Interfaces:**
- Consumes: versioned JSON fixtures and the same `CompositionCoordinator` used by the production adapter.
- Produces: `npm --prefix frontend run release-gate -- --profile L1|L2|L3|all`, JSON report under `runtime/evals/results/`, concise stdout summary, and nonzero exit when the requested target fails.

- [ ] **Step 1: Add fixture contract tests before fixtures**

Validate that every level has deterministic, recorded-LLM, and coordinator E2E cases; every case declares level/stage/expected outcome/hard-gate impact/evidence; recordings carry provider/model/prompt/schema/recordedAt/version metadata and no raw secrets.

- [ ] **Step 2: Verify RED and add the smallest complete matrix**

Run: `npm --prefix frontend test -- src/runtime/release-gate/scenario-runner.test.ts`
Expected: initially FAIL for missing fixtures, then PASS.

- [ ] **Step 3: Run real offline L1/L2/L3 scenarios**

L1 invokes the recorded semantic runner through the existing single-capability boundary. L2 invokes the production coordinator with fake READ Gateway. L3 invokes the same coordinator plus existing plan-aware fake/sandbox Action continuation; no live service is contacted.

- [ ] **Step 4: Implement and test CLI/report behavior**

Use the existing `vite-node` binary already installed with Vitest. Inject clock/code version in tests, write only redacted runtime output, and make two identical normalized runs produce identical case/metric/decision content.

- [ ] **Step 5: Run the gate twice**

Run: `npm --prefix frontend run release-gate -- --profile all`
Expected: exit 0, `L3_ACTION_GOVERNED`, live smoke `not_run`, and two reports whose normalized results match.

---

### Task 6: Documentation, full verification, and Native evidence

**Files:**
- Modify: `docs/runbooks/22-end-to-end-agent-eval-release-gate.md`
- Modify: `docs/runbooks/README.md`
- Modify: `README.md`
- Modify: `docs/wiki/sap-nexus-agent-technical-architecture.md`
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
- Modify: `docs/wiki/sap-nexus-agent-technology-selection.md` only where current-status claims require alignment.
- Create: `docs/superpowers/reports/2026-08-05-sap-nexus-end-to-end-agent-eval-release-gate-verify.md`
- Modify: `docs/comet/changes/sap-nexus-end-to-end-agent-eval-release-gate/verification.md`

**Interfaces:**
- Consumes: actual test/gate outputs and Native acceptance IDs.
- Produces: exact maturity claims, verification report, current evidence receipts, and archived Native specs.

- [ ] **Step 1: Update docs only from proven results**

Mark the highest offline maturity actually passed. State explicitly that live SAP READ/WRITE smoke is `not_run`; do not claim Knowledge/RAG or live composition.

- [ ] **Step 2: Run project verification**

```bash
npm --prefix frontend run verify
.venv/bin/python -m pytest agent/tests -q
scripts/verify-agent-callplan-evidence.sh
.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json
openspec list --json
openspec validate --all --strict
npm --prefix frontend run release-gate -- --profile all
git diff --check
git status --short
```

Expected: all commands pass; release decision is `L3_ACTION_GOVERNED`; live smoke remains `not_run`.

- [ ] **Step 3: Review scope and evidence**

Reread the brief, both complete specs, all 42 acceptance items, the implementation diff, and runtime report. Record only checks actually run; bind current receipts using `comet native evidence format`.

- [ ] **Step 4: Complete Native Verify and automatic Archive**

Advance with exact implementation artifacts, repair any failed acceptance, preview archive, and follow the Runtime continuation until `done`.
