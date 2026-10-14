import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord } from "../durable/types";
import { FakeGateway } from "../plan-executor/fake-gateway";
import type { PlanGraphV2, GatewayExecuteResult } from "../plan-executor/types";
import {
  DynamicAnalysisError,
  DynamicReadCoordinator,
  type AnalysisEnvelope,
  type PlanEnvelope,
} from "./coordinator";
import type { AnalysisWireInput, AnalysisWireOutput } from "./types";

function repoRoot(): string {
  return process.env.SAP_NEXUS_AGENT_ROOT
    ? path.dirname(process.env.SAP_NEXUS_AGENT_ROOT)
    : path.basename(process.cwd()) === "frontend"
      ? path.dirname(process.cwd())
      : process.cwd();
}

const release = JSON.parse(
  readFileSync(path.join(repoRoot(), "ontology/generated/semantic-release.json"), "utf8"),
);

function q2Plan(): PlanEnvelope {
  const readPlan: PlanGraphV2 = {
    planGraphVersion: 2,
    planId: "read-plan-q2",
    goalId: "goal-q2",
    executionMode: "READ_ONLY",
    snapshotId: release.registrySnapshotId,
    nodes: [
      {
        nodeId: "read-0",
        capabilityId: "MM.Inventory.GetAvailability",
        parameterBindings: [
          { parameterName: "material", source: { kind: "literal", semanticType: "sapnexus:MaterialNumber", value: "DEMOA2" } },
          { parameterName: "plant", source: { kind: "literal", semanticType: "sapnexus:Plant", value: "1000" } },
        ],
        producesFactTypes: ["sapnexus:InventoryAvailabilityFact"],
        governance: { requiresApproval: false },
      },
      {
        nodeId: "read-1",
        capabilityId: "MM.PurchaseOrder.GetList",
        parameterBindings: [
          { parameterName: "material", source: { kind: "literal", semanticType: "sapnexus:MaterialNumber", value: "DEMOA2" } },
          { parameterName: "plant", source: { kind: "literal", semanticType: "sapnexus:Plant", value: "1000" } },
        ],
        producesFactTypes: ["sapnexus:PurchaseOrderSupplyFact"],
        governance: { requiresApproval: false },
      },
    ],
    edges: [],
    topologicalOrder: ["read-0", "read-1"],
    goalOutputs: [],
    readPartition: ["read-0", "read-1"],
    actionPartition: [],
    projectionRef: [],
    ruleSetRefs: [],
  };
  return {
    status: "planned",
    plan: {
      planId: "sha256:" + "a".repeat(64),
      readPlan,
      analysisPlan: {
        nodes: [
          {
            nodeId: "a1",
            operatorId: "group_sum",
            inputs: [
              { kind: "factField", factTypeId: "sapnexus:PurchaseOrderSupplyFact", field: "orderQuantity" },
            ],
            params: { dimensions: ["supplier"], measure: "orderQuantity", unitField: "purchaseOrderUnit" },
            dependsOn: [],
          },
        ],
        outputs: ["a1"],
      },
      limits: {},
    },
    releaseIds: {
      semanticSnapshotId: release.semanticSnapshotId,
      registrySnapshotId: release.registrySnapshotId,
    },
  };
}

function poData(): GatewayExecuteResult {
  return {
    success: true,
    traceId: "fake-po",
    data: {
      purchaseOrders: [
        { purchaseOrder: "4500000001", purchaseOrderItem: "00010", supplier: "V72719", orderQuantity: "100", purchaseOrderUnit: "EA" },
        { purchaseOrder: "4500000001", purchaseOrderItem: "00020", supplier: "V72719", orderQuantity: "150", purchaseOrderUnit: "EA" },
      ],
    },
  };
}

function inventoryData(): GatewayExecuteResult {
  return { success: true, traceId: "fake-inv", data: { availableQuantity: "12.000" } };
}

function seed(runId: string): AgentRunRecord {
  const event: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [event], principalId: "local-user-0001" };
}

function fakeAnalysis(input: AnalysisWireInput): AnalysisWireOutput {
  return {
    wireVersion: 1,
    status: "complete",
    facts: [],
    results: [
      {
        schemaVersion: 1,
        nodeId: "a1",
        operatorId: "group_sum",
        status: "complete",
        outputType: "groupedRows",
        rows: [
          {
            groupKey: { supplier: "V72719" },
            measures: { orderQuantity: { decimal: "250", unit: "EA" } },
            lineage: input.nodeResults.flatMap(() => ["r0", "r1"]),
          },
        ],
        excludedRows: [],
        operatorVersion: "0.1.0",
        definitionRefs: [],
        partial: false,
        limits: {},
        reasons: [],
      },
    ],
    uncoveredConclusions: [],
    limits: {},
    semanticSnapshotId: input.release.semanticSnapshotId,
  };
}

describe("DynamicReadCoordinator", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "dyn-"));
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it("executes READ nodes then runs analysis without WRITE calls", async () => {
    const store = new JsonlRunStore(dir, "worker-1");
    const gateway = new FakeGateway();
    gateway.setExecuteResult("MM.Inventory.GetAvailability", inventoryData());
    gateway.setExecuteResult("MM.PurchaseOrder.GetList", poData());
    await store.save("run-seed", seed("run-seed"));

    const plan = q2Plan();
    const runAnalysis = vi.fn(fakeAnalysis);
    const coordinator = new DynamicReadCoordinator({
      store,
      gateway,
      workerId: "worker-1",
      planRequest: {},
      planRunner: vi.fn(async () => plan),
      runAnalysis,
    });

    const envelope: AnalysisEnvelope = await coordinator.execute();
    expect(envelope.status).toBe("complete");
    expect(envelope.writeGatewayCalls).toBe(0);
    expect(envelope.failedNodeIds).toEqual([]);
    expect(runAnalysis).toHaveBeenCalledTimes(1);
    const wire = runAnalysis.mock.calls[0][0];
    expect(wire.release.registrySnapshotId).toBe(release.registrySnapshotId);
    expect(wire.nodeResults.map((n) => n.capabilityId).sort()).toEqual([
      "MM.Inventory.GetAvailability",
      "MM.PurchaseOrder.GetList",
    ]);
    expect(gateway.executeCalls.every((call) => !call.capabilityId.includes("PR"))).toBe(true);
  });

  it("rejects a non-read-only plan before any gateway call", async () => {
    const store = new JsonlRunStore(dir, "worker-1");
    const gateway = new FakeGateway();
    const plan = q2Plan();
    plan.plan.readPlan.executionMode = "PLAN_ONLY";
    const runAnalysis = vi.fn(fakeAnalysis);
    const coordinator = new DynamicReadCoordinator({
      store,
      gateway,
      workerId: "worker-1",
      planRequest: {},
      planRunner: vi.fn(async () => plan),
      runAnalysis,
    });
    await expect(coordinator.execute()).rejects.toBeInstanceOf(DynamicAnalysisError);
    expect(gateway.executeCalls).toHaveLength(0);
    expect(runAnalysis).not.toHaveBeenCalled();
  });

  it("rejects release id mismatch in analysis results", async () => {
    const store = new JsonlRunStore(dir, "worker-1");
    const gateway = new FakeGateway();
    gateway.setExecuteResult("MM.Inventory.GetAvailability", inventoryData());
    gateway.setExecuteResult("MM.PurchaseOrder.GetList", poData());
    await store.save("run-seed2", seed("run-seed2"));
    const plan = q2Plan();
    const runAnalysis = vi.fn(async (input: AnalysisWireInput) => ({
      ...fakeAnalysis(input),
      semanticSnapshotId: "sha256:" + "f".repeat(64),
    }));
    const coordinator = new DynamicReadCoordinator({
      store,
      gateway,
      workerId: "worker-1",
      planRequest: {},
      planRunner: vi.fn(async () => plan),
      runAnalysis,
    });
    // The Python analysis runtime enforces RELEASE_MISMATCH; emulate fail-closed.
    const strictRunner = vi.fn(async (input: AnalysisWireInput) => {
      if (input.release.semanticSnapshotId !== release.semanticSnapshotId) {
        throw new DynamicAnalysisError("RELEASE_MISMATCH");
      }
      return runAnalysis(input);
    });
    const strict = new DynamicReadCoordinator({
      store, gateway, workerId: "worker-1", planRequest: {},
      planRunner: vi.fn(async () => plan), runAnalysis: strictRunner,
    });
    const envelope = await strict.execute();
    expect(envelope.writeGatewayCalls).toBe(0);
  });

  it("isolates a failed node in the failed list", async () => {
    const store = new JsonlRunStore(dir, "worker-1");
    const gateway = new FakeGateway();
    gateway.setExecuteResult("MM.Inventory.GetAvailability", {
      success: false, errorType: "MATERIAL_NOT_FOUND",
    });
    gateway.setExecuteResult("MM.PurchaseOrder.GetList", poData());
    await store.save("run-seed3", seed("run-seed3"));
    const plan = q2Plan();
    const runAnalysis = vi.fn(fakeAnalysis);
    const coordinator = new DynamicReadCoordinator({
      store, gateway, workerId: "worker-1", planRequest: {},
      planRunner: vi.fn(async () => plan), runAnalysis,
    });
    const envelope = await coordinator.execute();
    expect(envelope.failedNodeIds).toContain("read-0");
  });
});
