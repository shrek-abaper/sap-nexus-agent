import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import { PLACEHOLDER_PRINCIPAL, type TrustedPrincipal } from "../principal/types";
import type { PlanGraphV2 } from "../plan-executor/types";
import type { MaterialSupplySnapshot, PlanExecutionRecord } from "../projection/types";
import type { RecommendationPlan } from "../recommendation/types";
import { applyRunEvent, createInitialSnapshot } from "../run-state-machine";
import {
  PlanActionContinuation,
  type ActionGateway,
  type ActionGatewayRequest,
  type ActionGovernanceInput,
} from "./action-governance";

const NOW = "2026-08-05T08:00:00.000Z";
const DECIDED_AT = "2026-08-05T08:01:00.000Z";
const CONTINUED_AT = "2026-08-05T08:02:00.000Z";
const EXPIRES_AT = "2026-08-05T08:10:00.000Z";
const temporaryDirectories: string[] = [];

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

class FakeGateway implements ActionGateway {
  approveCalls = 0;
  executeCalls = 0;
  lastRequest: ActionGatewayRequest | null = null;

  async approve() {
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

function createStore(workerId: string) {
  const directory = mkdtempSync(path.join(os.tmpdir(), "sap-nexus-plan-action-runtime-"));
  temporaryDirectories.push(directory);
  return { directory, store: new JsonlRunStore(directory, workerId) };
}

async function seedRun(store: JsonlRunStore) {
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

function actionInput(overrides: Partial<ActionGovernanceInput> = {}): ActionGovernanceInput {
  const plan: PlanGraphV2 = {
    planGraphVersion: 2,
    planId: "plan-1",
    goalId: "goal-1",
    executionMode: "READ_THEN_SINGLE_ACTION",
    snapshotId: "snapshot-1",
    nodes: [
      { nodeId: "read-1", capabilityId: "MM.Inventory.GetAvailability", parameterBindings: [], producesFactTypes: ["InventoryFact"], governance: { requiresApproval: false } },
      { nodeId: "read-2", capabilityId: "MM.PurchaseOrder.GetList", parameterBindings: [], producesFactTypes: ["PurchaseOrderFact"], governance: { requiresApproval: false } },
      { nodeId: "action-1", capabilityId: "MM.PR.CreateDraft", parameterBindings: [], producesFactTypes: [], governance: { requiresApproval: true } },
    ],
    edges: [],
    topologicalOrder: ["read-1", "read-2", "action-1"],
    goalOutputs: [],
    readPartition: ["read-1", "read-2"],
    actionPartition: ["action-1"],
    projectionRef: [{ projectionId: "MaterialSupplySnapshot", version: "1.0.0" }],
    ruleSetRefs: ["material-shortage@1.0.0"],
  };
  const planExecution: PlanExecutionRecord = {
    runId: "run-1",
    snapshotId: "snapshot-1",
    nodeLedgerSummary: [
      { nodeId: "read-1", state: "SUCCEEDED", nodeExecutedAt: NOW },
      { nodeId: "read-2", state: "SUCCEEDED", nodeExecutedAt: NOW },
      { nodeId: "action-1", state: "BLOCKED_APPROVAL" },
    ],
    asOf: NOW,
    succeededNodes: ["read-1", "read-2"],
    failedNodes: [],
    missingFacts: [],
  };
  const projection: MaterialSupplySnapshot = {
    projectionId: "MaterialSupplySnapshot",
    projectionVersion: "1.0.0",
    snapshotId: "snapshot-1",
    asOf: NOW,
    sourceFreshness: [
      { nodeId: "read-1", nodeExecutedAt: NOW, dataAsOf: NOW },
      { nodeId: "read-2", nodeExecutedAt: NOW, dataAsOf: NOW },
    ],
    completeness: "complete",
    facts: [{
      factId: "fact-inventory",
      agentTraceId: "agent-trace-1",
      traceId: "trace-1",
      gatewayTraceId: "gateway-read-1",
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
    }],
    lineage: [],
    missingFacts: [],
    failedNodes: [],
    limitations: [],
    outputHash: "projection-hash-1",
  };
  const projectionRef = { projectionId: "MaterialSupplySnapshot", version: "1.0.0", outputHash: "projection-hash-1" };
  const recommendation: RecommendationPlan = {
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
    limitations: [{ code: "SANDBOX_ONLY", detail: "No live SAP WRITE in verification", sourceRefs: ["proposal-1"] }],
    rejectedAlternatives: [],
    actionProposal: {
      proposalId: "proposal-1",
      snapshotId: "snapshot-1",
      projectionRef,
      capabilityId: "MM.PR.CreateDraft",
      status: "pending_approval",
      parameters: { material: "MAT-1", plant: "1000", quantity: 3, unit: "EA", delivery_date: "2026-08-15", purchasing_group: "001" },
      parameterSources: {
        material: [{ kind: "fact", ref: "fact-inventory", field: "material" }],
        plant: [{ kind: "fact", ref: "fact-inventory", field: "plant" }],
        quantity: [{ kind: "constraint", ref: "requiredQuantity" }],
        unit: [{ kind: "fact", ref: "fact-inventory", field: "unit" }],
        delivery_date: [{ kind: "constraint", ref: "targetDate" }],
        purchasing_group: [{ kind: "constraint", ref: "purchasingGroup" }],
      },
      factsUsed: ["fact-inventory"],
      ruleSetRefs: ["material-shortage@1.0.0"],
      proposalHash: "proposal-hash-1",
    },
  };
  return {
    runId: "run-1",
    traceId: "trace-1",
    principal: PLACEHOLDER_PRINCIPAL,
    plan,
    planExecution,
    projection,
    recommendation,
    capabilityVersion: "2.1.0",
    capabilityStatus: "active",
    createdAt: NOW,
    expiresAt: EXPIRES_AT,
    ...overrides,
  };
}

describe("durable Plan Action runtime", () => {
  it("persists one pending approval with its complete display evidence and no Gateway call", async () => {
    const { store } = createStore("worker-a");
    await seedRun(store);
    const gateway = new FakeGateway();
    const runtime = new PlanActionContinuation(store, gateway, "worker-a");

    const pending = await runtime.prepare(actionInput());
    const reloaded = await store.load("run-1");
    const snapshot = reloaded!.events.reduce(applyRunEvent, createInitialSnapshot("run-1"));

    expect(pending).toMatchObject({
      status: "pending",
      parameterSources: { material: [{ kind: "fact", ref: "fact-inventory", field: "material" }] },
      factRefs: ["fact-inventory"],
      limitations: [{ code: "SANDBOX_ONLY" }],
    });
    expect(reloaded?.pendingOutcome).toMatchObject({
      status: "awaiting_approval",
      approvalRecord: { approvalId: pending.approvalId, status: "pending" },
      data: { actionGovernance: { schema: "sap-nexus.plan-action-governance.v1" } },
    });
    expect(reloaded?.events.map((event) => event.type)).toEqual([
      "run_started",
      "plan_compiled",
      "plan_node_state",
      "plan_node_state",
      "plan_node_state",
      "fact_emitted",
      "projection_completed",
      "recommendation_completed",
      "action_proposed",
      "approval_updated",
    ]);
    expect(reloaded?.events.slice(1).every((event) => (
      event.traceId === "trace-1" && event.snapshotId === "snapshot-1"
    ))).toBe(true);
    expect(snapshot).toMatchObject({ state: "awaiting_approval", hitlState: "awaiting_human_approval" });
    expect(gateway.executeCalls).toBe(0);
  });

  it("reloads the authoritative subject from durable state before Gateway execution", async () => {
    const { store } = createStore("worker-a");
    await seedRun(store);
    const gateway = new FakeGateway();
    const runtime = new PlanActionContinuation(store, gateway, "worker-a");
    const pending = await runtime.prepare(actionInput());
    const approved = await runtime.recordDecision(
      "run-1",
      pending.approvalId,
      "approve",
      PLACEHOLDER_PRINCIPAL,
      DECIDED_AT,
    );
    const durable = await store.load("run-1");
    const data = durable?.pendingOutcome?.data ?? {};
    const envelope = data.actionGovernance as Record<string, unknown>;
    const current = envelope.input as ActionGovernanceInput;
    await store.appendPendingOutcome("run-1", {
      ...durable!.pendingOutcome!,
      approvalRecord: approved.approvalRecord,
      data: {
        ...data,
        actionGovernance: {
          ...envelope,
          input: { ...current, capabilityVersion: "2.2.0" },
        },
      },
    });

    const outcome = await runtime.executeDurable(
      "run-1",
      pending.approvalId,
      PLACEHOLDER_PRINCIPAL,
      CONTINUED_AT,
    );
    const blockedRun = await store.load("run-1");

    expect(outcome).toMatchObject({ status: "blocked", errorType: "APPROVAL_SUBJECT_MISMATCH" });
    expect(blockedRun?.pendingOutcome).toMatchObject({ status: "blocked", errorType: "APPROVAL_SUBJECT_MISMATCH" });
    expect(blockedRun?.events.at(-1)).toMatchObject({
      type: "run_failed",
      error: { errorType: "APPROVAL_SUBJECT_MISMATCH" },
    });
    expect(gateway.approveCalls).toBe(0);
    expect(gateway.executeCalls).toBe(0);
  });

  it("executes once across a restart and appends replay-only approval/action evidence", async () => {
    const { directory, store } = createStore("worker-a");
    await seedRun(store);
    const gateway = new FakeGateway();
    const runtime = new PlanActionContinuation(store, gateway, "worker-a");
    const pending = await runtime.prepare(actionInput());
    await runtime.recordDecision("run-1", pending.approvalId, "approve", PLACEHOLDER_PRINCIPAL, DECIDED_AT);

    const first = await runtime.executeDurable("run-1", pending.approvalId, PLACEHOLDER_PRINCIPAL, CONTINUED_AT);
    const restarted = new PlanActionContinuation(new JsonlRunStore(directory, "worker-b"), gateway, "worker-b");
    const retry = await restarted.executeDurable("run-1", pending.approvalId, PLACEHOLDER_PRINCIPAL, "2026-08-05T08:03:00.000Z");
    const repeatedDecision = await restarted.recordDecision(
      "run-1",
      pending.approvalId,
      "approve",
      PLACEHOLDER_PRINCIPAL,
      "2026-08-05T08:03:00.000Z",
    );
    const replayed = await new JsonlRunStore(directory, "reader").load("run-1");

    expect(retry).toEqual(first);
    expect(repeatedDecision).toEqual(first);
    expect(gateway.executeCalls).toBe(1);
    expect(replayed?.events.map((event) => event.type).slice(-4)).toEqual([
      "approval_updated",
      "action_executed",
      "action_executed",
      "run_completed",
    ]);
    const snapshot = replayed!.events.reduce(applyRunEvent, createInitialSnapshot("run-1"));
    expect(snapshot).toMatchObject({ state: "completed", hitlState: "approved" });
    const actionEvent = replayed?.events.slice().reverse().find((event) => event.type === "action_executed");
    expect(actionEvent?.artifact?.payload).not.toHaveProperty("rawSapPayload");
  });

  it("treats same-process continuation instances as competing lease owners", async () => {
    const { directory, store } = createStore("shared-worker");
    await seedRun(store);
    const gateway = new FakeGateway();
    const firstRuntime = new PlanActionContinuation(store, gateway, "shared-worker");
    const secondRuntime = new PlanActionContinuation(
      new JsonlRunStore(directory, "shared-worker"),
      gateway,
      "shared-worker",
    );
    const pending = await firstRuntime.prepare(actionInput());
    await firstRuntime.recordDecision("run-1", pending.approvalId, "approve", PLACEHOLDER_PRINCIPAL, DECIDED_AT);

    const outcomes = await Promise.all([
      firstRuntime.executeDurable("run-1", pending.approvalId, PLACEHOLDER_PRINCIPAL, CONTINUED_AT),
      secondRuntime.executeDurable("run-1", pending.approvalId, PLACEHOLDER_PRINCIPAL, CONTINUED_AT),
    ]);

    expect(outcomes.some((outcome) => outcome.status === "executed")).toBe(true);
    expect(outcomes.some((outcome) => outcome.status === "in_progress")).toBe(true);
    expect(gateway.executeCalls).toBe(1);
  });

  it("records revoke durably and never calls Gateway", async () => {
    const { store } = createStore("worker-a");
    await seedRun(store);
    const gateway = new FakeGateway();
    const runtime = new PlanActionContinuation(store, gateway, "worker-a");
    const pending = await runtime.prepare(actionInput());

    const outcome = await runtime.revokeDurable(
      "run-1",
      pending.approvalId,
      PLACEHOLDER_PRINCIPAL,
      "user_cancelled",
      DECIDED_AT,
    );

    expect(outcome).toMatchObject({ status: "revoked", approvalRecord: { status: "revoked" } });
    expect((await store.load("run-1"))?.events.at(-1)?.artifact?.payload).toMatchObject({
      data: { status: "revoked", revocationReason: "user_cancelled" },
    });
    expect(gateway.executeCalls).toBe(0);
  });

  it("closes rejected and expired approval streams without calling Gateway", async () => {
    const rejectedStore = createStore("worker-reject").store;
    const expiredStore = createStore("worker-expire").store;
    await seedRun(rejectedStore);
    await seedRun(expiredStore);
    const gateway = new FakeGateway();
    const rejectedRuntime = new PlanActionContinuation(rejectedStore, gateway, "worker-reject");
    const expiredRuntime = new PlanActionContinuation(expiredStore, gateway, "worker-expire");
    const rejectedPending = await rejectedRuntime.prepare(actionInput());
    const expiredPending = await expiredRuntime.prepare(actionInput());

    const rejected = await rejectedRuntime.recordDecision(
      "run-1",
      rejectedPending.approvalId,
      "reject",
      PLACEHOLDER_PRINCIPAL,
      DECIDED_AT,
    );
    const expired = await expiredRuntime.recordDecision(
      "run-1",
      expiredPending.approvalId,
      "approve",
      PLACEHOLDER_PRINCIPAL,
      "2026-08-05T08:11:00.000Z",
    );

    expect(rejected).toMatchObject({ status: "rejected" });
    expect(expired).toMatchObject({ status: "expired", errorType: "APPROVAL_EXPIRED" });
    expect((await rejectedStore.load("run-1"))?.events.at(-1)).toMatchObject({
      type: "run_failed",
      error: { errorType: "APPROVAL_REJECTED" },
    });
    expect((await expiredStore.load("run-1"))?.events.at(-1)).toMatchObject({
      type: "run_failed",
      error: { errorType: "APPROVAL_EXPIRED" },
    });
    expect(gateway.executeCalls).toBe(0);
  });

  it("fails closed without revealing a run to a different principal", async () => {
    const { store } = createStore("worker-a");
    await seedRun(store);
    const runtime = new PlanActionContinuation(store, new FakeGateway(), "worker-a");
    const pending = await runtime.prepare(actionInput());
    const other: TrustedPrincipal = {
      principalId: "other-user",
      role: "operator",
      dataScope: { tenantId: "default" },
    };

    await expect(runtime.recordDecision("run-1", pending.approvalId, "approve", other, DECIDED_AT))
      .rejects.toThrow("Agent run not found");
  });
});
