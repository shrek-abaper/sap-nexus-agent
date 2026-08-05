import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { WorkbenchOutcome } from "../durable/types";
import { PLACEHOLDER_PRINCIPAL, type TrustedPrincipal } from "../principal/types";
import type { PlanGraphV2 } from "../plan-executor/types";
import type { MaterialSupplySnapshot, PlanExecutionRecord } from "../projection/types";
import type { RecommendationPlan } from "../recommendation/types";
import {
  ActionGovernanceError,
  PlanActionContinuation,
  createPlanApprovalRecord,
  decidePlanApproval,
  revokePlanApproval,
  validatePlanApproval,
  type ActionGovernanceInput,
  type ActionGateway,
  type ActionGatewayRequest,
} from "./action-governance";

const NOW = "2026-08-05T08:00:00.000Z";
const EXPIRES = "2026-08-05T08:10:00.000Z";
const OTHER_PRINCIPAL: TrustedPrincipal = {
  principalId: "other-user",
  role: "operator",
  dataScope: { tenantId: "default" },
};

const temporaryDirectories: string[] = [];

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

function graph(): PlanGraphV2 {
  return {
    planGraphVersion: 2,
    planId: "plan-1",
    goalId: "goal-1",
    executionMode: "READ_THEN_SINGLE_ACTION",
    snapshotId: "snapshot-1",
    nodes: [
      {
        nodeId: "node-inventory",
        capabilityId: "MM.Inventory.GetAvailability",
        parameterBindings: [],
        producesFactTypes: ["sapnexus:MaterialAvailabilityFact"],
        governance: { requiresApproval: false },
      },
      {
        nodeId: "node-po",
        capabilityId: "MM.PurchaseOrder.GetList",
        parameterBindings: [],
        producesFactTypes: ["sapnexus:PurchaseOrderSupplyFact"],
        governance: { requiresApproval: false },
      },
      {
        nodeId: "node-action",
        capabilityId: "MM.PR.CreateDraft",
        parameterBindings: [],
        producesFactTypes: [],
        governance: { requiresApproval: true },
      },
    ],
    edges: [],
    topologicalOrder: ["node-inventory", "node-po", "node-action"],
    goalOutputs: [],
    readPartition: ["node-inventory", "node-po"],
    actionPartition: ["node-action"],
    projectionRef: [{ projectionId: "MaterialSupplySnapshot", version: "1.0.0" }],
    ruleSetRefs: ["material-shortage@1.0.0"],
  };
}

function execution(): PlanExecutionRecord {
  return {
    runId: "run-1",
    snapshotId: "snapshot-1",
    nodeLedgerSummary: [
      { nodeId: "node-inventory", state: "SUCCEEDED", nodeExecutedAt: NOW },
      { nodeId: "node-po", state: "SUCCEEDED", nodeExecutedAt: NOW },
      { nodeId: "node-action", state: "BLOCKED_APPROVAL" },
    ],
    asOf: NOW,
    succeededNodes: ["node-inventory", "node-po"],
    failedNodes: [],
    missingFacts: [],
  };
}

function projection(): MaterialSupplySnapshot {
  return {
    projectionId: "MaterialSupplySnapshot",
    projectionVersion: "1.0.0",
    snapshotId: "snapshot-1",
    asOf: NOW,
    sourceFreshness: [
      { nodeId: "node-inventory", nodeExecutedAt: NOW, dataAsOf: NOW },
      { nodeId: "node-po", nodeExecutedAt: NOW, dataAsOf: NOW },
    ],
    completeness: "complete",
    facts: [
      {
        factId: "fact-inventory",
        agentTraceId: "trace-agent-1",
        traceId: "trace-1",
        gatewayTraceId: "gateway-1",
        domain: "MM",
        businessObject: "MaterialAvailability",
        predicate: "availableQuantity",
        value: 7,
        unit: "EA",
        deterministic: true,
        confidence: 1,
        source: { capabilityId: "MM.Inventory.GetAvailability" },
        evidence: [],
        material: "MAT-1",
        plant: "1000",
        asOf: NOW,
      },
    ],
    lineage: [],
    missingFacts: [],
    failedNodes: [],
    limitations: [],
    outputHash: "projection-hash-1",
  };
}

function recommendation(): RecommendationPlan {
  const projectionRef = {
    projectionId: "MaterialSupplySnapshot",
    version: "1.0.0",
    outputHash: "projection-hash-1",
  };
  return {
    recommendationId: "recommendation-1",
    planHash: "recommendation-hash-1",
    status: "RECOMMEND",
    summaryCode: "SHORTAGE_ACTION_PROPOSED",
    snapshotId: "snapshot-1",
    projectionRef,
    ruleSetRefs: ["material-shortage@1.0.0"],
    facts: [],
    rules: [{ ruleId: "material-shortage", ruleSetRef: "material-shortage@1.0.0", triggered: true }],
    assumptions: [],
    limitations: [],
    rejectedAlternatives: [],
    actionProposal: {
      proposalId: "proposal-1",
      snapshotId: "snapshot-1",
      projectionRef,
      capabilityId: "MM.PR.CreateDraft",
      status: "pending_approval",
      parameters: {
        material: "MAT-1",
        plant: "1000",
        quantity: 3,
        unit: "EA",
        delivery_date: "2026-08-15",
        purchasing_group: "001",
      },
      parameterSources: {
        material: [{ kind: "fact", ref: "fact-inventory", field: "material" }],
        plant: [{ kind: "fact", ref: "fact-inventory", field: "plant" }],
        quantity: [
          { kind: "constraint", ref: "requiredQuantity" },
          { kind: "fact", ref: "fact-inventory", field: "value" },
        ],
        unit: [{ kind: "fact", ref: "fact-inventory", field: "unit" }],
        delivery_date: [{ kind: "constraint", ref: "targetDate" }],
        purchasing_group: [{ kind: "constraint", ref: "purchasingGroup" }],
      },
      factsUsed: ["fact-inventory"],
      ruleSetRefs: ["material-shortage@1.0.0"],
      proposalHash: "proposal-hash-1",
    },
  };
}

function input(overrides: Partial<ActionGovernanceInput> = {}): ActionGovernanceInput {
  return {
    runId: "run-1",
    traceId: "trace-1",
    principal: PLACEHOLDER_PRINCIPAL,
    plan: graph(),
    planExecution: execution(),
    projection: projection(),
    recommendation: recommendation(),
    capabilityVersion: "registry-v2",
    capabilityStatus: "active",
    createdAt: NOW,
    expiresAt: EXPIRES,
    ...overrides,
  };
}

class FakeActionGateway implements ActionGateway {
  approveCalls = 0;
  executeCalls = 0;
  lastRequest: ActionGatewayRequest | null = null;

  async approve(): Promise<void> {
    this.approveCalls += 1;
  }

  async execute(request: ActionGatewayRequest) {
    this.executeCalls += 1;
    this.lastRequest = request;
    return {
      success: true,
      traceId: "gateway-action-1",
      data: { prNumber: "10000001" },
      returnMessages: [{ type: "S", message: "created" }],
    };
  }
}

function durableStore(workerId: string) {
  const directory = mkdtempSync(path.join(os.tmpdir(), "sap-nexus-action-governance-"));
  temporaryDirectories.push(directory);
  return { directory, store: new JsonlRunStore(directory, workerId) };
}

async function saveRun(store: JsonlRunStore) {
  await store.save("run-1", {
    runId: "run-1",
    query: "create a governed PR draft",
    principalId: PLACEHOLDER_PRINCIPAL.principalId,
    events: [{
      runId: "run-1",
      sequence: 1,
      timestamp: NOW,
      type: "run_started",
      state: "running",
    }],
  });
}

describe("PlanApprovalRecord", () => {
  it("binds the complete immutable subject without executing Gateway", () => {
    const record = createPlanApprovalRecord(input());

    expect(record).toMatchObject({
      runId: "run-1",
      planId: "plan-1",
      snapshotId: "snapshot-1",
      actionNodeId: "node-action",
      capabilityId: "MM.PR.CreateDraft",
      capabilityVersion: "registry-v2",
      proposalId: "proposal-1",
      proposalHash: "proposal-hash-1",
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      tenantId: "default",
      status: "pending",
      confirmingPrincipalId: null,
      separationOfDutyResult: "not_applicable",
    });
    expect(record.planHash).toMatch(/^[a-f0-9]{64}$/);
    expect(record.parameterSnapshotHash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(record.factSetHash).toMatch(/^[a-f0-9]{64}$/);
    expect(record.ruleSetHash).toMatch(/^[a-f0-9]{64}$/);
    expect(record.subjectHash).toMatch(/^[a-f0-9]{64}$/);
  });

  it("rejects incomplete or inconsistent approval subjects", () => {
    const invalidCases: ActionGovernanceInput[] = [
      input({ plan: { ...graph(), actionPartition: [] } }),
      input({ plan: { ...graph(), actionPartition: ["node-action", "node-po"] } }),
      input({ projection: { ...projection(), completeness: "partial" } }),
      input({ projection: { ...projection(), snapshotId: "snapshot-drift" } }),
      input({ planExecution: { ...execution(), failedNodes: ["node-po"] } }),
      input({ recommendation: { ...recommendation(), actionProposal: undefined } }),
      input({ capabilityStatus: "disabled" }),
    ];

    for (const invalid of invalidCases) {
      expect(() => createPlanApprovalRecord(invalid)).toThrowError(ActionGovernanceError);
    }
  });

  it("records an explicit run-owner decision and rejects cross-principal decisions", () => {
    const pending = createPlanApprovalRecord(input());
    const approved = decidePlanApproval(pending, "approve", PLACEHOLDER_PRINCIPAL, "2026-08-05T08:01:00.000Z");

    expect(approved).toMatchObject({
      status: "approved",
      confirmingPrincipalId: PLACEHOLDER_PRINCIPAL.principalId,
      decidedAt: "2026-08-05T08:01:00.000Z",
      separationOfDutyResult: "not_applicable",
    });
    expect(() => decidePlanApproval(pending, "approve", OTHER_PRINCIPAL, "2026-08-05T08:01:00.000Z"))
      .toThrowError(/principal/i);
    expect(() => decidePlanApproval(approved, "approve", PLACEHOLDER_PRINCIPAL, "2026-08-05T08:02:00.000Z"))
      .toThrowError(/pending/i);
  });

  it("supports reject, expire and revoke as non-executable terminal states", () => {
    const pending = createPlanApprovalRecord(input());
    expect(decidePlanApproval(pending, "reject", PLACEHOLDER_PRINCIPAL, "2026-08-05T08:01:00.000Z").status)
      .toBe("rejected");
    expect(() => decidePlanApproval(pending, "approve", PLACEHOLDER_PRINCIPAL, "2026-08-05T08:11:00.000Z"))
      .toThrowError(/expired/i);

    const approved = decidePlanApproval(pending, "approve", PLACEHOLDER_PRINCIPAL, "2026-08-05T08:01:00.000Z");
    const revoked = revokePlanApproval(approved, PLACEHOLDER_PRINCIPAL, "user_cancelled", "2026-08-05T08:02:00.000Z");
    expect(revoked).toMatchObject({ status: "revoked", revocationReason: "user_cancelled" });
    expect(validatePlanApproval(revoked, input(), PLACEHOLDER_PRINCIPAL, "2026-08-05T08:03:00.000Z"))
      .toMatchObject({ valid: false, errorType: "APPROVAL_REVOKED" });
  });

  it("fails closed for every governed subject drift", () => {
    const pending = createPlanApprovalRecord(input());
    const approved = decidePlanApproval(pending, "approve", PLACEHOLDER_PRINCIPAL, "2026-08-05T08:01:00.000Z");
    const changedRecommendation = recommendation();
    changedRecommendation.actionProposal = {
      ...changedRecommendation.actionProposal!,
      proposalHash: "changed-proposal",
    };
    const changedProjection = projection();
    changedProjection.outputHash = "changed-projection";
    changedProjection.facts = [{ ...changedProjection.facts[0], value: 6 }];

    const drifts: ActionGovernanceInput[] = [
      input({ principal: OTHER_PRINCIPAL }),
      input({ plan: { ...graph(), snapshotId: "changed-snapshot" } }),
      input({ plan: { ...graph(), planId: "changed-plan" } }),
      input({ plan: { ...graph(), actionPartition: ["node-po"] } }),
      input({ capabilityVersion: "registry-v3" }),
      input({ capabilityStatus: "disabled" }),
      input({ projection: changedProjection }),
      input({ recommendation: changedRecommendation }),
      input({ recommendation: { ...recommendation(), ruleSetRefs: ["material-shortage@2.0.0"] } }),
    ];

    for (const current of drifts) {
      expect(validatePlanApproval(approved, current, current.principal, "2026-08-05T08:02:00.000Z").valid)
        .toBe(false);
    }
  });
});

describe("PlanActionContinuation", () => {
  it("executes the approved Action once and returns the same durable result on retry", async () => {
    const { directory, store } = durableStore("worker-a");
    await saveRun(store);
    const gateway = new FakeActionGateway();
    const approved = decidePlanApproval(
      createPlanApprovalRecord(input()),
      "approve",
      PLACEHOLDER_PRINCIPAL,
      "2026-08-05T08:01:00.000Z",
    );
    const continuation = new PlanActionContinuation(store, gateway, "worker-a");

    const first = await continuation.execute(approved, input(), PLACEHOLDER_PRINCIPAL, "2026-08-05T08:02:00.000Z");
    const restarted = new PlanActionContinuation(new JsonlRunStore(directory, "worker-b"), gateway, "worker-b");
    const replayed = await restarted.execute(approved, input(), PLACEHOLDER_PRINCIPAL, "2026-08-05T08:03:00.000Z");

    expect(first).toEqual(replayed);
    expect(first).toMatchObject({
      status: "executed",
      approvalRecord: { status: "executed" },
      actionResult: { success: true, data: { prNumber: "10000001" } },
    });
    expect(gateway.approveCalls).toBe(1);
    expect(gateway.executeCalls).toBe(1);
    expect(gateway.lastRequest).toMatchObject({
      capabilityId: "MM.PR.CreateDraft",
      approvalId: approved.approvalId,
      registrySnapshotId: "snapshot-1",
      capabilityVersion: "registry-v2",
      approvalSubjectHash: approved.subjectHash,
    });
    expect(Object.keys(gateway.lastRequest ?? {})).not.toContain("rfcName");
    expect(Object.keys(gateway.lastRequest ?? {})).not.toContain("bindingId");
  });

  it("does not call Gateway for unapproved, revoked, expired or drifted subjects", async () => {
    const { store } = durableStore("worker-a");
    await saveRun(store);
    const gateway = new FakeActionGateway();
    const pending = createPlanApprovalRecord(input());
    const approved = decidePlanApproval(pending, "approve", PLACEHOLDER_PRINCIPAL, "2026-08-05T08:01:00.000Z");
    const revoked = revokePlanApproval(approved, PLACEHOLDER_PRINCIPAL, "cancelled", "2026-08-05T08:02:00.000Z");
    const continuation = new PlanActionContinuation(store, gateway, "worker-a");
    const drifted = input({ capabilityVersion: "registry-v3" });

    const outcomes: WorkbenchOutcome[] = [];
    outcomes.push(await continuation.execute(pending, input(), PLACEHOLDER_PRINCIPAL, "2026-08-05T08:03:00.000Z"));
    outcomes.push(await continuation.execute(revoked, input(), PLACEHOLDER_PRINCIPAL, "2026-08-05T08:03:00.000Z"));
    outcomes.push(await continuation.execute(approved, input(), PLACEHOLDER_PRINCIPAL, "2026-08-05T08:11:00.000Z"));
    outcomes.push(await continuation.execute(approved, drifted, PLACEHOLDER_PRINCIPAL, "2026-08-05T08:03:00.000Z"));

    expect(outcomes.every((outcome) => outcome.status === "blocked")).toBe(true);
    expect(gateway.approveCalls).toBe(0);
    expect(gateway.executeCalls).toBe(0);
  });

  it("allows only one concurrent worker to call Gateway", async () => {
    const { directory, store } = durableStore("worker-a");
    await saveRun(store);
    const gateway = new FakeActionGateway();
    const approved = decidePlanApproval(
      createPlanApprovalRecord(input()),
      "approve",
      PLACEHOLDER_PRINCIPAL,
      "2026-08-05T08:01:00.000Z",
    );
    const a = new PlanActionContinuation(store, gateway, "worker-a");
    const b = new PlanActionContinuation(new JsonlRunStore(directory, "worker-b"), gateway, "worker-b");

    const outcomes = await Promise.all([
      a.execute(approved, input(), PLACEHOLDER_PRINCIPAL, "2026-08-05T08:02:00.000Z"),
      b.execute(approved, input(), PLACEHOLDER_PRINCIPAL, "2026-08-05T08:02:00.000Z"),
    ]);

    expect(outcomes.some((outcome) => outcome.status === "executed")).toBe(true);
    expect(outcomes.every((outcome) => ["executed", "in_progress"].includes(outcome.status))).toBe(true);
    expect(gateway.executeCalls).toBe(1);
  });
});
