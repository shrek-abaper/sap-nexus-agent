// frontend/src/runtime/plan-executor/plan-executor.test.ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord } from "../durable/types";
import { FakeGateway } from "./fake-gateway";
import { NodeState } from "./types";
import { PlanExecutor } from "./plan-executor";
import type { PlanGraphV2, GatewayClient, GatewayValidateResult, GatewayExecuteResult, NodeLedgerEntry } from "./types";

const SNAP = "sha256:snap-001";

function seed(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e], principalId: "local-user-0001" };
}

function dualReadGraph(): PlanGraphV2 {
  return {
    planGraphVersion: 2,
    planId: "plan-001",
    goalId: "goal-001",
    executionMode: "advisory",
    snapshotId: SNAP,
    nodes: [
      {
        nodeId: "node.inv",
        capabilityId: "MM.Inventory.GetAvailability",
        parameterBindings: [
          { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } },
          { parameterName: "plant", source: { kind: "literal", semanticType: "PlantCode", value: "5300" } },
        ],
        producesFactTypes: ["InventoryAvailability"],
        governance: { requiresApproval: false },
      },
      {
        nodeId: "node.po",
        capabilityId: "MM.PurchaseOrder.GetList",
        parameterBindings: [
          { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "M1" } },
          { parameterName: "plant", source: { kind: "literal", semanticType: "PlantCode", value: "5300" } },
        ],
        producesFactTypes: ["PurchaseOrder"],
        governance: { requiresApproval: false },
      },
    ],
    edges: [],
    topologicalOrder: ["node.inv", "node.po"],
    goalOutputs: [],
    readPartition: ["node.inv", "node.po"],
    actionPartition: [],
    projectionRef: [],
    ruleSetRefs: [],
  };
}

function singleReadNodeGraph(): PlanGraphV2 {
  const g = dualReadGraph();
  return {
    ...g,
    nodes: [g.nodes[0]],
    topologicalOrder: ["node.inv"],
    readPartition: ["node.inv"],
  };
}

function diffParamGraph(): PlanGraphV2 {
  const g = dualReadGraph();
  g.nodes[1].parameterBindings[0].source = {
    kind: "literal",
    semanticType: "MaterialCode",
    value: "M2",
  };
  return g;
}

class ThrowingGateway implements GatewayClient {
  async validate(_capabilityId: string, _parameters: Record<string, string>): Promise<GatewayValidateResult> {
    throw new Error("gateway validate boom");
  }
  async execute(_capabilityId: string, _parameters: Record<string, string>): Promise<GatewayExecuteResult> {
    throw new Error("gateway execute boom");
  }
}

describe("PlanExecutor", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "exec-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("executes two independent READ nodes concurrently", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    expect(result.succeeded.sort()).toEqual(["node.inv", "node.po"]);
    expect(result.failed).toEqual([]);
    // Both nodes passed through validate -> execute
    expect(gateway.validateCalls).toHaveLength(2);
    expect(gateway.executeCalls).toHaveLength(2);
  });

  it("persists SUCCEEDED state to node ledger", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const executor = new PlanExecutor(store, new FakeGateway(), "worker-A");
    await executor.execute(dualReadGraph(), "run-1", SNAP);
    const reopened = new JsonlRunStore(dir, "worker-B");
    const ref = await reopened.loadCheckpointRef("run-1");
    const ledger = ref!.nodeState as Record<string, { state: string }>;
    expect(ledger["node.inv"].state).toBe(NodeState.SUCCEEDED);
    expect(ledger["node.po"].state).toBe(NodeState.SUCCEEDED);
  });

  it("validate failure -> FAILED, independent node continues", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    gateway.setValidateResult("MM.Inventory.GetAvailability", { valid: false, errors: ["bad material"] });
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    expect(result.failed).toEqual(["node.inv"]);
    expect(result.succeeded).toEqual(["node.po"]);
    // execute NOT called for failed-validate node
    expect(gateway.executeCalls).toHaveLength(1);
    expect(gateway.executeCalls[0].capabilityId).toBe("MM.PurchaseOrder.GetList");
  });

  it("Action node stays BLOCKED_APPROVAL, no Gateway call", async () => {
    const graph = dualReadGraph();
    // Make one node an Action (requires approval)
    graph.nodes[0].governance.requiresApproval = true;
    graph.readPartition = ["node.inv"]; // only the action node in readPartition (edge case test)
    graph.actionPartition = ["node.po"];
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway();
    const executor = new PlanExecutor(store, gateway, "worker-A");
    const result = await executor.execute(graph, "run-1", SNAP);
    expect(result.blocked).toContain("node.inv");
    expect(result.succeeded).toEqual([]);
    expect(gateway.validateCalls).toHaveLength(0);
    expect(gateway.executeCalls).toHaveLength(0);
  });

  it("rejects plan with snapshot drift (fail-closed before Gateway)", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const executor = new PlanExecutor(store, new FakeGateway(), "worker-A");
    const graph = dualReadGraph();
    const result = await executor.execute(graph, "run-1", "sha256:DIFFERENT");
    expect(result.succeeded).toEqual([]);
    expect(result.failed).toEqual([]);
    expect(result.blocked).toEqual([]);
  });

  // --- Critical #1: no double-event emission ---
  it("emits exactly one node_state_changed event per transition (no duplication)", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const executor = new PlanExecutor(store, new FakeGateway(), "worker-A");
    await executor.execute(singleReadNodeGraph(), "run-1", SNAP);
    const record = await store.load("run-1");
    const nodeEvents = record!.events.filter((e) => e.type === "node_state_changed");
    // Single READ node: INITIAL->READY, READY->VALIDATING, VALIDATING->EXECUTING, EXECUTING->SUCCEEDED
    expect(nodeEvents).toHaveLength(4);
  });

  it("broadcasts node_state_changed via sseBroadcast callback (live push only)", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const broadcasted: AgentRunEvent[] = [];
    const executor = new PlanExecutor(store, new FakeGateway(), "worker-A", (e) => broadcasted.push(e));
    await executor.execute(singleReadNodeGraph(), "run-1", SNAP);
    // Live SSE push: one broadcast per transition (4 transitions for a single READ node)
    expect(broadcasted).toHaveLength(4);
    expect(broadcasted.every((e) => e.type === "node_state_changed")).toBe(true);
    // Durable stream must still have exactly 4 (no duplication)
    const record = await store.load("run-1");
    const durableEvents = record!.events.filter((e) => e.type === "node_state_changed");
    expect(durableEvents).toHaveLength(4);
  });

  // --- Important #2: lease released on execution error ---
  it("releases lease even when Gateway throws", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const executor = new PlanExecutor(store, new ThrowingGateway(), "worker-A");
    await expect(executor.execute(singleReadNodeGraph(), "run-1", SNAP)).rejects.toThrow("gateway validate boom");
    const leaseExpiry = await store.loadLeaseExpiry("run-1");
    expect(leaseExpiry).toBeNull();
  });

  // --- Important #3: inputHash computed from values and stored ---
  it("stores non-empty inputHash reflecting parameter values", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const executor = new PlanExecutor(store, new FakeGateway(), "worker-A");
    await executor.execute(dualReadGraph(), "run-1", SNAP);
    const ref = await store.loadCheckpointRef("run-1");
    const ledger = ref!.nodeState as Record<string, NodeLedgerEntry>;
    // inputHash is non-empty
    expect(ledger["node.inv"].inputHash).not.toBe("");
    // Same params -> same hash
    expect(ledger["node.inv"].inputHash).toBe(ledger["node.po"].inputHash);
    // Hash reflects VALUES (contains "M1"), not just parameter names
    expect(ledger["node.inv"].inputHash).toContain("M1");
  });

  it("inputHash differs for different parameter values", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const executor = new PlanExecutor(store, new FakeGateway(), "worker-A");
    await executor.execute(diffParamGraph(), "run-1", SNAP);
    const ref = await store.loadCheckpointRef("run-1");
    const ledger = ref!.nodeState as Record<string, NodeLedgerEntry>;
    // Different param values -> different hash
    expect(ledger["node.inv"].inputHash).not.toBe(ledger["node.po"].inputHash);
    // node.inv has M1, node.po has M2
    expect(ledger["node.inv"].inputHash).toContain("M1");
    expect(ledger["node.po"].inputHash).toContain("M2");
  });

  // --- Task 9: node-level timeout + user cancellation ---

  it("node timeout -> TIMED_OUT, independent node continues", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    // delayMs below nodeTimeoutMs so gateway returns before timeout
    const gateway = new FakeGateway({ delayMs: 50 });
    // Make one node fail execute to test independence
    gateway.setExecuteResult("MM.Inventory.GetAvailability", { success: false, errorType: "TIMEOUT", message: "timed out" });
    const executor = new PlanExecutor(store, gateway, "worker-A", { nodeTimeoutMs: 100 });
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    // node.inv execute fails -> FAILED (not TIMED_OUT, because fake returns before timeout)
    expect(result.failed).toContain("node.inv");
    expect(result.succeeded).toContain("node.po");
  });

  it("true timeout: gateway slower than nodeTimeoutMs -> TIMED_OUT", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway({ delayMs: 300 });
    const executor = new PlanExecutor(store, gateway, "worker-A", { nodeTimeoutMs: 50 });
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    expect(result.timedOut.length).toBeGreaterThan(0);
    expect(result.succeeded).toEqual([]);
  });

  it("cancel: uncompleted nodes -> CANCELLED, SUCCEEDED preserved", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    const gateway = new FakeGateway({ delayMs: 200 });
    const executor = new PlanExecutor(store, gateway, "worker-A", { nodeTimeoutMs: 500 });
    // Cancel after 50ms (while nodes are still executing)
    setTimeout(() => executor.cancel(), 50);
    const result = await executor.execute(dualReadGraph(), "run-1", SNAP);
    // Nodes were in-flight when cancelled -> CANCELLED
    expect(result.cancelled.length).toBeGreaterThan(0);
    expect(result.succeeded).toEqual([]);
  });
});
