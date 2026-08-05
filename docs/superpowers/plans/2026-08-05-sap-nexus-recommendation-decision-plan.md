# SAP Nexus Recommendation Decision Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic component/Eval recommendation layer that consumes a governed `MaterialSupplySnapshot`, an exact registered RuleSet, and explicit user constraints to produce a replayable `RecommendationPlan` with at most one non-executable `pending_approval` ActionProposal.

**Architecture:** Add a focused TypeScript module next to the existing projection runtime. A snapshot-bound `RuleSetRegistry` owns exact rule lookup; a pure `RecommendationDecisionEngine` performs sufficiency gates and the fixed material-shortage calculation, then hashes canonical output. Tests exercise real registry and engine behavior, while a repository-level JSON case set supplies reviewable Eval inputs.

**Tech Stack:** TypeScript 5.8, Vitest 3, existing `canonicalJson`/SHA-256 utilities, Native Comet artifacts, Markdown source-of-truth docs.

## Global Constraints

- Component/Eval only: do not connect the production orchestrator, `projectionRef`, SSE, Workbench, or durable runtime.
- Do not call LLM, Gateway, JCo, OData, or SAP; do not create ApprovalRecord and do not execute SAP WRITE.
- RuleSet, projection, decision request, and proposal capability must share one non-empty RegistrySnapshot identity.
- `partial` and `incomplete` projections cannot form proposals; RuleSet freshness has no hidden default.
- PO ordered quantity does not reduce shortage because the current fact contract lacks delivery date, open quantity, and receipt status.
- Proposal status is only `pending_approval`; output has one optional `actionProposal`, never an executable action list.
- Work on the current branch and do not commit unless the user explicitly asks.

---

### Task 1: Recommendation contracts and snapshot-bound RuleSet registry

**Files:**
- Create: `frontend/src/runtime/recommendation/types.ts`
- Create: `frontend/src/runtime/recommendation/rule-set-registry.ts`
- Create: `frontend/src/runtime/recommendation/rule-set-registry.test.ts`

**Interfaces:**
- Consumes: `MaterialSupplySnapshot` from `frontend/src/runtime/projection/types.ts`.
- Produces: `MaterialShortageRuleSet`, `DecisionRegistrySnapshot`, `RecommendationDecisionRequest`, `RecommendationPlan`, `RuleSetRegistry`, and `RuleSetRegistryError`.

- [x] **Step 1: Write failing registry tests**

```typescript
const registry = new RuleSetRegistry("snapshot-1");
registry.register(ruleSet);
expect(registry.resolve("material-shortage-pr", "1.0.0")).toEqual(ruleSet);
expect(() => registry.resolve("missing", "1.0.0")).toThrowError(
  expect.objectContaining({ code: "RULESET_NOT_REGISTERED" }),
);
expect(() => registry.register({ ...ruleSet })).toThrowError(
  expect.objectContaining({ code: "RULESET_DUPLICATE" }),
);
expect(() => registry.register({ ...ruleSet, maxProjectionAgeMs: 2 })).toThrowError(
  expect.objectContaining({ code: "RULESET_CONFLICT" }),
);
```

- [x] **Step 2: Run the registry test and confirm RED**

Run: `npm --prefix frontend test -- src/runtime/recommendation/rule-set-registry.test.ts`

Expected: FAIL because the recommendation registry module does not exist.

- [x] **Step 3: Implement minimal domain types and exact tuple registry**

```typescript
export type MaterialShortageRuleSet = {
  ruleSetId: string;
  version: string;
  registrySnapshotId: string;
  inputProjection: { projectionId: string; version: string };
  requiredConstraints: Array<"requiredQuantity" | "targetDate" | "purchasingGroup">;
  maxProjectionAgeMs: number;
  actionCapabilityId: "MM.PR.CreateDraft";
  strategy: "material-shortage";
};

export class RuleSetRegistry {
  constructor(readonly snapshotId: string) {}
  register(ruleSet: MaterialShortageRuleSet): void;
  resolve(ruleSetId: string, version: string): MaterialShortageRuleSet;
}
```

Use a collision-safe nested map, reject empty/mismatched snapshot ids and non-positive/non-finite age, and distinguish exact duplicate from conflicting content with `canonicalJson`.

- [x] **Step 4: Run the registry test and confirm GREEN**

Run: `npm --prefix frontend test -- src/runtime/recommendation/rule-set-registry.test.ts`

Expected: registry tests pass with no warnings.

### Task 2: Deterministic shortage decision and proposal

**Files:**
- Create: `frontend/src/runtime/recommendation/decision-engine.ts`
- Create: `frontend/src/runtime/recommendation/decision-engine.test.ts`
- Modify: `frontend/src/runtime/recommendation/types.ts`

**Interfaces:**
- Consumes: `RecommendationDecisionRequest`, `RuleSetRegistry`, and normalized projection facts.
- Produces: `RecommendationDecisionEngine.decide(request): RecommendationPlan`.

- [x] **Step 1: Write failing happy-path, replay, and no-action tests**

```typescript
const plan = engine.decide(request({ requiredQuantity: 10 }));
expect(plan.status).toBe("RECOMMEND");
expect(plan.actionProposal?.parameters.quantity).toBe(3);
expect(plan.actionProposal?.status).toBe("pending_approval");
expect(Object.keys(plan.actionProposal?.parameterSources ?? {}).sort()).toEqual([
  "delivery_date", "material", "plant", "purchasing_group", "quantity", "unit",
]);

expect(engine.decide(reorderedFactsRequest)).toEqual(plan);
expect(engine.decide(request({ requiredQuantity: 7 })).status).toBe("NO_ACTION");
expect(engine.decide(request({ requiredQuantity: 7 })).actionProposal).toBeUndefined();
```

The literal fixture contains availability 7 EA and PO order quantity 99; the expected proposal remains 3 to prove PO quantity is not treated as available supply.

- [x] **Step 2: Run the engine test and confirm RED**

Run: `npm --prefix frontend test -- src/runtime/recommendation/decision-engine.test.ts`

Expected: FAIL because `RecommendationDecisionEngine` does not exist.

- [x] **Step 3: Implement the minimal pure engine**

```typescript
export class RecommendationDecisionEngine {
  constructor(private readonly ruleSets: RuleSetRegistry) {}
  decide(request: RecommendationDecisionRequest): RecommendationPlan;
}
```

Normalize facts by stable business/fact id order. Resolve the exact RuleSet, validate the common snapshot/projection/action declaration, require one valid availability fact, calculate `requiredQuantity - availableQuantity`, populate all six parameter sources, and hash the proposal and plan with canonical JSON. Keep `assumptions: []`; add rejected alternative `PO_QUANTITY_NOT_CONFIRMED_SUPPLY` when PO facts exist.

- [x] **Step 4: Run the engine test and confirm GREEN**

Run: `npm --prefix frontend test -- src/runtime/recommendation/decision-engine.test.ts`

Expected: proposal, replay, PO rejection, and no-action tests pass.

### Task 3: Clarification, fail-closed gates, and reviewable Eval data

**Files:**
- Modify: `frontend/src/runtime/recommendation/decision-engine.test.ts`
- Modify: `frontend/src/runtime/recommendation/decision-engine.ts`
- Create: `frontend/src/runtime/recommendation/recommendation-eval.test.ts`
- Create: `evals/recommendation_decision_cases.json`

**Interfaces:**
- Consumes: literal Eval cases with `id`, input overrides, expected status/limitations, and optional proposal quantity.
- Produces: explicit `CLARIFY` or `INSUFFICIENT_INPUT` plans with stable limitation codes and no proposal.

- [x] **Step 1: Add failing unit tests for every fail-closed branch**

```typescript
it.each([
  ["requiredQuantity", "MISSING_CONSTRAINT_REQUIRED_QUANTITY"],
  ["targetDate", "MISSING_CONSTRAINT_TARGET_DATE"],
  ["purchasingGroup", "MISSING_CONSTRAINT_PURCHASING_GROUP"],
])("clarifies missing %s", (field, code) => {
  const plan = engine.decide(requestWithout(field));
  expect(plan.status).toBe("CLARIFY");
  expect(plan.limitations).toContainEqual(expect.objectContaining({ code }));
  expect(plan.actionProposal).toBeUndefined();
});
```

Add literal assertions for partial, incomplete, stale/invalid time, unknown RuleSet, snapshot mismatch, unsupported/unregistered Action, multiple/conflicting availability facts, invalid unit, and invalid constraints.

- [x] **Step 2: Run the engine tests and confirm RED for the new branches**

Run: `npm --prefix frontend test -- src/runtime/recommendation/decision-engine.test.ts`

Expected: the new cases fail with incorrect status or missing limitation code.

- [x] **Step 3: Implement ordered sufficiency gates**

Gate order is deterministic: RuleSet lookup -> shared snapshot -> projection tuple -> completeness -> freshness -> missing constraints -> constraint validity -> availability fact uniqueness/shape -> Action declaration -> shortage decision. Every early result still includes stable facts/rule refs, empty assumptions, limitations, rejected alternatives, and a canonical plan hash.

- [x] **Step 4: Run the unit tests and confirm GREEN**

Run: `npm --prefix frontend test -- src/runtime/recommendation/decision-engine.test.ts`

Expected: all success, clarify, and fail-closed branches pass.

- [x] **Step 5: Add the JSON Eval matrix and a failing data-driven test**

```json
{
  "schema": "sap-nexus.recommendation-decision-eval.v1",
  "cases": [
    { "id": "shortage-proposal", "expectedStatus": "RECOMMEND", "expectedProposalQuantity": 3 },
    { "id": "missing-demand", "omitConstraint": "requiredQuantity", "expectedStatus": "CLARIFY" },
    { "id": "stale-projection", "projectionAgeMs": 86400001, "expectedStatus": "INSUFFICIENT_INPUT" }
  ]
}
```

The complete file also covers no-action, each missing constraint, partial/incomplete, unknown/conflicting rules, snapshot/action/fact/unit failures, deterministic replay, and at-most-one/no-side-effect shape.

- [x] **Step 6: Run the Eval test, implement only missing fixture adaptation, and confirm GREEN**

Run: `npm --prefix frontend test -- src/runtime/recommendation/recommendation-eval.test.ts`

Expected: every named Eval case passes against the real registry and engine without mocks.

### Task 4: Workstream closeout and full verification

**Files:**
- Modify: `docs/runbooks/18-recommendation-decision-plan.md`
- Modify: `docs/runbooks/README.md`
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
- Modify: `docs/wiki/sap-nexus-agent-technical-architecture.md`
- Modify: `docs/wiki/sap-nexus-agent-technology-selection.md`
- Modify: `docs/superpowers/specs/2026-08-03-sap-nexus-complete-agent-roadmap-design.md`
- Create: `docs/comet/changes/sap-nexus-recommendation-decision-plan/verification.md`

**Interfaces:**
- Consumes: actual verification outputs and Native acceptance IDs/receipts.
- Produces: an honest component/Eval maturity statement, Runbook 19 next entry, and a Native verification matrix ready for Archive.

- [x] **Step 1: Run focused and required project checks**

```bash
npm --prefix frontend run verify
.venv/bin/python -m pytest agent/tests -q
.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
git diff --check
```

Expected: every command exits 0; no command executes SAP WRITE.

- [x] **Step 2: Update current source-of-truth docs with actual results**

Mark Runbook 18 implemented/archived only after verification evidence exists. State that recommendation is component/Eval only, production orchestration remains deferred, no approval/write occurred, and Runbook 19 is the next entry. Preserve historical version rows.

- [x] **Step 3: Re-run doc-sensitive checks**

Run: `openspec validate --all --strict && git diff --check`

Expected: strict OpenSpec validation and whitespace checks pass.

- [x] **Step 4: Record fresh Native receipts and verification report**

Use `comet native receipt automated` for each command and `comet native receipt manual` for code/spec review facts, then format the acceptance evidence with `comet native evidence format`. Write the generated block unchanged under `# Acceptance evidence` and record commands, skipped checks, spec consistency, risks, and conclusion in `verification.md`.

- [x] **Step 5: Submit Verify pass and Archive**

Advance Build with all implementation/doc artifacts, follow the Runtime continuation into Verify, submit `pass` only after all 24 acceptance items have fresh receipts, run `comet native archive ... --dry-run`, then execute the exact automatic archive command returned by Runtime.

## Self-Review

- Spec coverage: Tasks 1-3 cover all registry, sufficiency, determinism, proposal, no-execution, and Eval requirements; Task 4 covers project regressions, documentation, Native evidence, and Archive.
- Placeholder scan: no `TBD`, deferred implementation placeholder, or unspecified error-handling step remains.
- Type consistency: `RuleSetRegistry`, `RecommendationDecisionRequest`, `RecommendationDecisionEngine.decide`, single `actionProposal`, and limitation/status names are consistent across tasks.
