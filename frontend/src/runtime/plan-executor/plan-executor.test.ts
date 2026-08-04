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
import type { PlanGraphV2 } from "./types";

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
});
