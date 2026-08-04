import { describe, expect, it } from "vitest";
import { NodeState, type NodeFactRecord, type PlanExecutorResult } from "../plan-executor/types";
import { ProjectionInputAssembler } from "./assembler";
import { createMaterialSupplyFactBuilderRegistry } from "./fact-builder";

const dataAsOf = "2026-08-04T00:00:00Z";
const nodeExecutedAt = "2026-08-04T00:00:01Z";

function nodeRecord(overrides: Partial<NodeFactRecord>): NodeFactRecord {
  return {
    nodeId: "node.inventory",
    agentTraceId: "run-1",
    capabilityId: "MM.Inventory.GetAvailability",
    parameters: { material: "MAT-1", plant: "PLANT-1" },
    producesFactTypes: ["InventoryAvailability"],
    gatewayTraceId: "gw-inventory",
    executeData: { availableQuantity: 7, unit: "EA", dataAsOf },
    nodeExecutedAt,
    ...overrides,
  };
}

function result(overrides: Partial<PlanExecutorResult> = {}): PlanExecutorResult {
  return {
    runId: "run-1",
    snapshotId: "snapshot-1",
    nodeLedger: {
      "node.inventory": {
        state: NodeState.SUCCEEDED,
        attempt: 1,
        inputHash: "inventory-input",
        resultRef: "inventory-result",
        traceSpan: null,
        updatedAt: nodeExecutedAt,
      },
      "node.po": {
        state: NodeState.SUCCEEDED,
        attempt: 1,
        inputHash: "po-input",
        resultRef: "po-result",
        traceSpan: null,
        updatedAt: nodeExecutedAt,
      },
      "node.failed": {
        state: NodeState.FAILED,
        attempt: 1,
        inputHash: "failed-input",
        resultRef: null,
        traceSpan: null,
        updatedAt: nodeExecutedAt,
      },
    },
    succeeded: ["node.po", "node.inventory"],
    succeededNodeResults: [
      nodeRecord({
        nodeId: "node.po",
        capabilityId: "MM.PurchaseOrder.GetList",
        producesFactTypes: ["PurchaseOrder"],
        gatewayTraceId: "gw-po",
        executeData: {
          purchaseOrders: [
            { purchaseOrder: "4500001", orderQuantity: 2, purchaseOrderUnit: "EA" },
          ],
          dataAsOf,
        },
      }),
      nodeRecord({}),
    ],
    failed: ["node.failed"],
    timedOut: [],
    cancelled: [],
    blocked: [],
    ...overrides,
  };
}

describe("ProjectionInputAssembler", () => {
  it("assembles deterministic facts only from succeeded node results", () => {
    const input = new ProjectionInputAssembler().assemble(
      result(),
      createMaterialSupplyFactBuilderRegistry(),
    );

    expect(input.facts.map((fact) => fact.source.factType)).toEqual([
      "InventoryAvailability",
      "PurchaseOrder",
    ]);
    expect(input.facts.every((fact) => fact.asOf === dataAsOf)).toBe(true);
    expect(input.facts.every((fact) => (
      fact.agentTraceId === "run-1"
      && fact.traceId === "run-1"
      && fact.gatewayTraceId !== "run-1"
    ))).toBe(true);
    expect(input.planExecutionRecord).toMatchObject({
      runId: "run-1",
      snapshotId: "snapshot-1",
      asOf: dataAsOf,
      succeededNodes: ["node.inventory", "node.po"],
      failedNodes: ["node.failed"],
      missingFacts: [],
    });
    expect(input.planExecutionRecord.nodeLedgerSummary).toContainEqual({
      nodeId: "node.failed",
      state: "FAILED",
    });
    expect(input.facts.some((fact) => fact.source.nodeId === "node.failed")).toBe(false);
  });

  it("records declared missing facts when a succeeded capability has no builder", () => {
    const unknown = nodeRecord({
      nodeId: "node.unknown",
      capabilityId: "MM.Unknown.Read",
      producesFactTypes: ["InventoryAvailability"],
    });
    const input = new ProjectionInputAssembler().assemble(
      result({
        nodeLedger: {
          "node.unknown": {
            state: NodeState.SUCCEEDED,
            attempt: 1,
            inputHash: "unknown-input",
            resultRef: "unknown-result",
            traceSpan: null,
            updatedAt: nodeExecutedAt,
          },
        },
        succeeded: ["node.unknown"],
        succeededNodeResults: [unknown],
        failed: [],
      }),
      createMaterialSupplyFactBuilderRegistry(),
    );

    expect(input.facts).toEqual([]);
    expect(input.planExecutionRecord.missingFacts).toEqual([
      { factType: "InventoryAvailability", reason: "no_fact_builder" },
    ]);
  });

  it("falls back to node execution time when Gateway freshness is absent", () => {
    const inventory = nodeRecord({ executeData: { availableQuantity: 7, unit: "EA" } });
    const input = new ProjectionInputAssembler().assemble(
      result({
        nodeLedger: { "node.inventory": result().nodeLedger["node.inventory"] },
        succeeded: ["node.inventory"],
        succeededNodeResults: [inventory],
        failed: [],
      }),
      createMaterialSupplyFactBuilderRegistry(),
    );

    expect(input.facts[0]?.asOf).toBe(nodeExecutedAt);
    expect(input.planExecutionRecord.asOf).toBe(nodeExecutedAt);
  });

  it("keeps the assembler boundary limited to executor result and builder registry", () => {
    expect(ProjectionInputAssembler.prototype.assemble.length).toBe(2);
  });
});
