import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { AgentRunRecord } from "../durable/types";
import { FakeGateway } from "../plan-executor/fake-gateway";
import type { PlanGraphV2 } from "../plan-executor/types";
import { PLACEHOLDER_PRINCIPAL } from "../principal/types";
import { CompositionCoordinator } from "./coordinator";

const SNAPSHOT_ID = "snapshot-release-1";
const NOW = "2026-08-05T01:00:00.000Z";

function seed(runId: string): AgentRunRecord {
  return {
    runId,
    query: "summarize material supply",
    principalId: PLACEHOLDER_PRINCIPAL.principalId,
    events: [{
      runId,
      sequence: 1,
      timestamp: NOW,
      type: "run_started",
      state: "running",
    }],
  };
}

function dualReadGraph(): PlanGraphV2 {
  const bindings = [
    { parameterName: "material", source: { kind: "literal" as const, semanticType: "MaterialCode", value: "MAT-1" } },
    { parameterName: "plant", source: { kind: "literal" as const, semanticType: "PlantCode", value: "P1" } },
  ];
  return {
    planGraphVersion: 2,
    planId: "plan-release-1",
    goalId: "goal-release-1",
    executionMode: "advisory",
    snapshotId: SNAPSHOT_ID,
    nodes: [
      {
        nodeId: "node.inventory",
        capabilityId: "MM.Inventory.GetAvailability",
        parameterBindings: bindings,
        producesFactTypes: ["InventoryAvailability"],
        governance: { requiresApproval: false },
      },
      {
        nodeId: "node.purchase-orders",
        capabilityId: "MM.PurchaseOrder.GetList",
        parameterBindings: bindings,
        producesFactTypes: ["PurchaseOrder"],
        governance: { requiresApproval: false },
      },
    ],
    edges: [],
    topologicalOrder: ["node.inventory", "node.purchase-orders"],
    goalOutputs: [],
    readPartition: ["node.inventory", "node.purchase-orders"],
    actionPartition: [],
    projectionRef: [],
    ruleSetRefs: [],
  };
}

function readToWriteGraph(): PlanGraphV2 {
  const graph = dualReadGraph();
  return {
    ...graph,
    executionMode: "READ_THEN_SINGLE_ACTION",
    nodes: [
      ...graph.nodes,
      {
        nodeId: "node.action",
        capabilityId: "MM.PR.CreateDraft",
        parameterBindings: [
          { parameterName: "quantity", source: { kind: "literal", semanticType: "Quantity", value: "10" } },
          { parameterName: "delivery_date", source: { kind: "literal", semanticType: "Date", value: "2026-08-15" } },
          { parameterName: "purchasing_group", source: { kind: "literal", semanticType: "PurchasingGroup", value: "601" } },
        ],
        producesFactTypes: [],
        governance: { requiresApproval: true },
      },
    ],
    topologicalOrder: [...graph.topologicalOrder, "node.action"],
    actionPartition: ["node.action"],
  };
}

function configuredGateway(): FakeGateway {
  const gateway = new FakeGateway();
  gateway.setExecuteResult("MM.Inventory.GetAvailability", {
    success: true,
    traceId: "gateway-inventory",
    data: {
      availableQuantity: 7,
      unit: "EA",
      material: "MAT-1",
      plant: "P1",
      dataAsOf: NOW,
    },
  });
  gateway.setExecuteResult("MM.PurchaseOrder.GetList", {
    success: true,
    traceId: "gateway-po",
    data: {
      purchaseOrders: [{
        purchaseOrder: "4500001",
        purchaseOrderItem: "10",
        orderQuantity: 5,
        purchaseOrderUnit: "EA",
        material: "MAT-1",
        plant: "P1",
      }],
      dataAsOf: NOW,
    },
  });
  return gateway;
}

describe("CompositionCoordinator", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "composition-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("runs the real executor, projection, recommendation, narrative, and durable evidence chain", async () => {
    const runId = "run-release-l2";
    const store = new JsonlRunStore(dir, "worker-release");
    await store.save(runId, seed(runId));
    const coordinator = new CompositionCoordinator({
      store,
      gateway: configuredGateway(),
      workerId: "worker-release",
      now: () => NOW,
    });

    const outcome = await coordinator.execute({
      runId,
      traceId: "trace-release-l2",
      principal: PLACEHOLDER_PRINCIPAL,
      handoff: { graph: dualReadGraph(), snapshotId: SNAPSHOT_ID },
      locale: "en",
    });

    expect(outcome.projection.completeness).toBe("complete");
    expect(new Set(outcome.projection.lineage.map((item) => item.factId)))
      .toEqual(new Set(outcome.facts.map((fact) => fact.factId)));
    expect(outcome.recommendation.status).toBe("CLARIFY");
    expect(outcome.actionGovernanceInput).toBeUndefined();
    expect(outcome.narrative.claims.every((claim) => claim.evidenceRefs.length > 0)).toBe(true);

    const durable = await store.load(runId);
    expect(durable?.events.map((event) => event.type)).toEqual(expect.arrayContaining([
      "plan_compiled",
      "plan_node_state",
      "fact_emitted",
      "projection_completed",
      "recommendation_completed",
      "narrative_completed",
      "run_completed",
    ]));
    expect(durable?.events.map((event) => event.sequence))
      .toEqual(durable?.events.map((_, index) => index + 1));
  });

  it("keeps a failed optional READ visible as an incomplete projection without an Action", async () => {
    const runId = "run-release-partial";
    const store = new JsonlRunStore(dir, "worker-release");
    await store.save(runId, seed(runId));
    const gateway = configuredGateway();
    gateway.setValidateResult("MM.PurchaseOrder.GetList", {
      valid: false,
      errors: ["synthetic timeout"],
    });
    const coordinator = new CompositionCoordinator({
      store,
      gateway,
      workerId: "worker-release",
      now: () => NOW,
    });

    const outcome = await coordinator.execute({
      runId,
      traceId: "trace-release-partial",
      principal: PLACEHOLDER_PRINCIPAL,
      handoff: { graph: dualReadGraph(), snapshotId: SNAPSHOT_ID },
      locale: "en",
    });

    expect(outcome.projection.completeness).toBe("incomplete");
    expect(outcome.projection.failedNodes).toEqual(["node.purchase-orders"]);
    expect(outcome.projection.limitations).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: "missing_optional" }),
    ]));
    expect(outcome.actionGovernanceInput).toBeUndefined();
  });

  it("forms one governed Action input when a fresh shortage plan supplies every rule constraint", async () => {
    const runId = "run-release-l3";
    const store = new JsonlRunStore(dir, "worker-release");
    await store.save(runId, seed(runId));
    const coordinator = new CompositionCoordinator({
      store,
      gateway: configuredGateway(),
      workerId: "worker-release",
      now: () => NOW,
    });

    const outcome = await coordinator.execute({
      runId,
      traceId: "trace-release-l3",
      principal: PLACEHOLDER_PRINCIPAL,
      handoff: { graph: readToWriteGraph(), snapshotId: SNAPSHOT_ID },
      locale: "en",
    });

    expect(outcome.recommendation.status).toBe("RECOMMEND");
    expect(outcome.recommendation.actionProposal).toMatchObject({
      capabilityId: "MM.PR.CreateDraft",
      status: "pending_approval",
      parameters: { quantity: 3, delivery_date: "2026-08-15", purchasing_group: "601" },
    });
    expect(outcome.actionGovernanceInput).toMatchObject({
      runId,
      traceId: "trace-release-l3",
      capabilityStatus: "active",
    });
    expect((await store.load(runId))?.events.at(-1)?.type).not.toBe("run_completed");
  });
});
