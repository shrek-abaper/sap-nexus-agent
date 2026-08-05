// frontend/src/runtime/plan-executor/plan-executor-recovery.test.ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord, WorkbenchOutcome } from "../durable/types";
import { FakeGateway } from "./fake-gateway";
import { NodeState } from "./types";
import { PlanExecutor } from "./plan-executor";
import { saveNodeLedger } from "./node-ledger";
import type { PlanGraphV2, NodeLedgerEntry } from "./types";

const SNAP = "sha256:snap-001";

function seed(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e], principalId: "local-user-0001" };
}

function dualReadGraph(): PlanGraphV2 {
  return {
    planGraphVersion: 2, planId: "p1", goalId: "g1", executionMode: "advisory", snapshotId: SNAP,
    nodes: [
      { nodeId: "node.inv", capabilityId: "MM.Inventory.GetAvailability", parameterBindings: [
        { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } },
      ], producesFactTypes: [], governance: { requiresApproval: false } },
      { nodeId: "node.po", capabilityId: "MM.PurchaseOrder.GetList", parameterBindings: [
        { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } },
      ], producesFactTypes: [], governance: { requiresApproval: false } },
    ],
    edges: [], topologicalOrder: ["node.inv", "node.po"], goalOutputs: [],
    readPartition: ["node.inv", "node.po"], actionPartition: [], projectionRef: [], ruleSetRefs: [],
  };
}

function singleReadGraph(): PlanGraphV2 {
  const graph = dualReadGraph();
  return {
    ...graph,
    nodes: [graph.nodes[0]],
    topologicalOrder: ["node.inv"],
    readPartition: ["node.inv"],
  };
}

class InterruptingMarkExecutedStore extends JsonlRunStore {
  private interrupted = false;

  constructor(
    dataDir: string,
    workerId: string,
    private readonly persistBeforeFailure: boolean,
  ) {
    super(dataDir, workerId);
  }

  override async markExecuted(key: string, result: WorkbenchOutcome): Promise<void> {
    if (!this.interrupted) {
      this.interrupted = true;
      if (this.persistBeforeFailure) {
        await super.markExecuted(key, result);
      }
      throw new Error("injected markExecuted interruption");
    }
    await super.markExecuted(key, result);
  }
}

function ledgerEntry(state: NodeState, attempt = 0): NodeLedgerEntry {
  return { state, attempt, inputHash: "material", resultRef: null, traceSpan: null, updatedAt: "2026-08-04T00:00:00Z" };
}

describe("PlanExecutor recovery", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "recov-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("restart skips SUCCEEDED nodes, resumes READY", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    // Pre-seed: node.inv SUCCEEDED, node.po not in ledger (will be READY)
    await saveNodeLedger(store, "run-1", SNAP, {
      "node.inv": ledgerEntry(NodeState.SUCCEEDED),
    });

    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);

    // node.inv skipped (SUCCEEDED), node.po executed
    expect(result.succeeded).toEqual(["node.inv", "node.po"]);
    // node.inv NOT re-executed
    const invValCalls = gateway.validateCalls.filter((c) => c.capabilityId === "MM.Inventory.GetAvailability");
    expect(invValCalls).toHaveLength(0);
    // node.po WAS executed
    const poValCalls = gateway.validateCalls.filter((c) => c.capabilityId === "MM.PurchaseOrder.GetList");
    expect(poValCalls).toHaveLength(1);
    expect(result.succeededNodeResults.map((record) => record.nodeId)).toEqual(["node.po"]);
  });

  it("FAILED node stays FAILED on restart (no auto-retry)", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, {
      "node.inv": ledgerEntry(NodeState.FAILED),
      "node.po": ledgerEntry(NodeState.SUCCEEDED),
    });

    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);

    // node.inv stays FAILED, not re-executed
    expect(result.failed).toEqual(["node.inv"]);
    expect(gateway.validateCalls).toHaveLength(0);
  });

  it("idempotent replay: same idempotency key returns recorded result, no re-execution", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));

    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");

    // First execution
    const result1 = await executor.execute(dualReadGraph(), "run-1", SNAP);
    expect(result1.succeeded).toHaveLength(2);
    const firstCallCount = gateway.validateCalls.length;

    // Second execution (replay) - should skip all SUCCEEDED
    const executor2 = new PlanExecutor(store, gateway, "worker-A");
    const result2 = await executor2.execute(dualReadGraph(), "run-1", SNAP);
    expect(result2.succeeded).toHaveLength(2);
    // No additional Gateway calls
    expect(gateway.validateCalls.length).toBe(firstCallCount);
  });

  it("restart restores succeeded node data without re-executing Gateway", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    gateway.setExecuteResult("MM.Inventory.GetAvailability", {
      success: true,
      traceId: "gw-inv",
      data: { availableQuantity: 7 },
    });

    const first = await new PlanExecutor(store, gateway, "worker-A").execute(
      dualReadGraph(),
      "run-1",
      SNAP
    );
    const firstExecuteCallCount = gateway.executeCalls.length;
    const second = await new PlanExecutor(store, gateway, "worker-A").execute(
      dualReadGraph(),
      "run-1",
      SNAP
    );

    expect(first.succeededNodeResults).toHaveLength(2);
    expect(second.succeededNodeResults).toEqual(first.succeededNodeResults);
    expect(first.succeededNodeResults.every((record) => record.agentTraceId === "run-1")).toBe(true);
    expect(second.succeededNodeResults.every((record) => record.agentTraceId === "run-1")).toBe(true);
    expect(second.succeededNodeResults.every(
      (record) => record.agentTraceId !== record.gatewayTraceId,
    )).toBe(true);
    expect(gateway.executeCalls).toHaveLength(firstExecuteCallCount);
  });

  it("fails closed without repeating Gateway when payload persistence fails", async () => {
    const store = new InterruptingMarkExecutedStore(dir, "worker-A", false);
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();

    await expect(new PlanExecutor(store, gateway, "worker-A").execute(
      singleReadGraph(),
      "run-1",
      SNAP,
    )).rejects.toThrow("injected markExecuted interruption");

    const reopened = new JsonlRunStore(dir, "worker-A");
    const interrupted = await reopened.loadCheckpointRef("run-1");
    expect(interrupted?.nodeState["node.inv"]).toMatchObject({
      state: NodeState.EXECUTING,
    });
    const executeCallsBeforeRestart = gateway.executeCalls.length;

    const recovered = await new PlanExecutor(reopened, gateway, "worker-A").execute(
      singleReadGraph(),
      "run-1",
      SNAP,
    );

    expect(recovered.failed).toEqual(["node.inv"]);
    expect(recovered.succeededNodeResults).toEqual([]);
    expect(gateway.executeCalls).toHaveLength(executeCallsBeforeRestart);
  });

  it("recovers persisted payload after interruption before durable success", async () => {
    const store = new InterruptingMarkExecutedStore(dir, "worker-A", true);
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    gateway.setExecuteResult("MM.Inventory.GetAvailability", {
      success: true,
      traceId: "gw-inv",
      data: { availableQuantity: 7 },
    });

    await expect(new PlanExecutor(store, gateway, "worker-A").execute(
      singleReadGraph(),
      "run-1",
      SNAP,
    )).rejects.toThrow("injected markExecuted interruption");

    const reopened = new JsonlRunStore(dir, "worker-A");
    const interrupted = await reopened.loadCheckpointRef("run-1");
    expect(interrupted?.nodeState["node.inv"]).toMatchObject({
      state: NodeState.EXECUTING,
    });
    const executeCallsBeforeRestart = gateway.executeCalls.length;

    const recovered = await new PlanExecutor(reopened, gateway, "worker-A").execute(
      singleReadGraph(),
      "run-1",
      SNAP,
    );

    expect(recovered.succeeded).toEqual(["node.inv"]);
    expect(recovered.succeededNodeResults).toEqual([
      expect.objectContaining({
        nodeId: "node.inv",
        gatewayTraceId: "gw-inv",
        executeData: { availableQuantity: 7 },
      }),
    ]);
    expect(gateway.executeCalls).toHaveLength(executeCallsBeforeRestart);
  });

  it("lease conflict -> fail-closed, no Gateway calls", async () => {
    const storeA = new JsonlRunStore(dir, "worker-A");
    const storeB = new JsonlRunStore(dir, "worker-B");
    await storeA.save("run-1", seed("run-1"));
    // Worker A holds lease
    await storeA.claim("run-1", "worker-A", 60_000);

    const gateway = new FakeGateway();
    const executor = new PlanExecutor(storeB, gateway, "worker-B");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);

    // Lease rejected -> no execution, no Gateway calls
    expect(result.succeeded).toEqual([]);
    expect(result.failed).toEqual([]);
    expect(gateway.validateCalls).toHaveLength(0);
    expect(gateway.executeCalls).toHaveLength(0);
  });

  // Direct idempotency store test: pre-seeded result for a non-SUCCEEDED node
  // must skip Gateway calls and transition straight to SUCCEEDED.
  it("idempotency store hit: pre-seeded result skips Gateway calls for non-SUCCEEDED node", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    // Pre-seed idempotency: node.inv already executed with same inputs
    // inputHash for dualReadGraph() = "material=M1" (single literal binding)
    await store.markExecuted("run-1:node.inv:0:material=M1", {
      status: "succeeded",
      gatewayTraceId: "cached-trace",
    });

    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);

    // node.inv: idempotency hit -> SUCCEEDED without Gateway validate/execute
    expect(result.succeeded).toContain("node.inv");
    const invValCalls = gateway.validateCalls.filter((c) => c.capabilityId === "MM.Inventory.GetAvailability");
    expect(invValCalls).toHaveLength(0);
    // node.po: no idempotency entry -> normal execution
    const poValCalls = gateway.validateCalls.filter((c) => c.capabilityId === "MM.PurchaseOrder.GetList");
    expect(poValCalls).toHaveLength(1);
    expect(result.succeededNodeResults.map((record) => record.nodeId)).not.toContain("node.inv");
  });

  it("idempotency replay restores a complete cached node result with its original time", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await store.markExecuted("run-1:node.inv:0:material=M1", {
      status: "succeeded",
      gatewayTraceId: "cached-trace",
      data: { availableQuantity: 7 },
      parameters: { material: "M1" },
      capabilityId: "MM.Inventory.GetAvailability",
      producesFactTypes: ["InventoryAvailability"],
      nodeExecutedAt: "2026-08-04T00:00:00Z",
    });

    const gateway = new FakeGateway();
    const result = await new PlanExecutor(store, gateway, "worker-A").execute(
      dualReadGraph(),
      "run-1",
      SNAP
    );

    expect(result.succeededNodeResults).toContainEqual({
      nodeId: "node.inv",
      agentTraceId: "run-1",
      capabilityId: "MM.Inventory.GetAvailability",
      parameters: { material: "M1" },
      producesFactTypes: ["InventoryAvailability"],
      gatewayTraceId: "cached-trace",
      executeData: { availableQuantity: 7 },
      nodeExecutedAt: "2026-08-04T00:00:00Z",
    });
    expect(gateway.executeCalls.map((call) => call.capabilityId)).not.toContain(
      "MM.Inventory.GetAvailability"
    );
  });

  it.each([
    { label: "missing", gatewayTraceId: undefined },
    { label: "blank", gatewayTraceId: "   " },
  ])("hydrates cached and existing success with a nullable Gateway trace when trace is $label", async ({ gatewayTraceId }) => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await store.markExecuted("run-1:node.inv:0:material=M1", {
      status: "succeeded",
      gatewayTraceId,
      data: { availableQuantity: 7 },
      parameters: { material: "M1" },
      capabilityId: "MM.Inventory.GetAvailability",
      producesFactTypes: ["InventoryAvailability"],
      nodeExecutedAt: "2026-08-04T00:00:00Z",
    });

    const gateway = new FakeGateway();
    const first = await new PlanExecutor(store, gateway, "worker-A").execute(
      dualReadGraph(),
      "run-1",
      SNAP
    );
    const second = await new PlanExecutor(store, gateway, "worker-A").execute(
      dualReadGraph(),
      "run-1",
      SNAP
    );

    expect(first.succeeded).toContain("node.inv");
    expect(second.succeeded).toContain("node.inv");
    expect(first.nodeLedger["node.inv"].state).toBe(NodeState.SUCCEEDED);
    expect(second.nodeLedger["node.inv"].state).toBe(NodeState.SUCCEEDED);
    expect(first.succeededNodeResults).toContainEqual(expect.objectContaining({
      nodeId: "node.inv",
      agentTraceId: "run-1",
      gatewayTraceId: null,
      executeData: { availableQuantity: 7 },
    }));
    expect(second.succeededNodeResults).toContainEqual(expect.objectContaining({
      nodeId: "node.inv",
      agentTraceId: "run-1",
      gatewayTraceId: null,
      executeData: { availableQuantity: 7 },
    }));
    expect(gateway.executeCalls.map((call) => call.capabilityId)).not.toContain(
      "MM.Inventory.GetAvailability"
    );
  });
});
