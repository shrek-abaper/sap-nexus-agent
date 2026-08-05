import { describe, expect, it } from "vitest";
import { computeOutputHash } from "./hash";
import {
  createOutputProjectionRegistry,
  materialSupplySnapshotProjection,
} from "./material-supply-snapshot";
import type { ProjectionInput, ReasoningFact } from "./types";

const dataAsOf = "2026-08-04T00:00:00Z";

function inventoryFact(overrides: Partial<ReasoningFact> = {}): ReasoningFact {
  return {
    factId: "inventory-1",
    agentTraceId: "run-1",
    traceId: "trace-inventory",
    gatewayTraceId: "gateway-inventory",
    domain: "MM",
    businessObject: "InventoryStock",
    predicate: "availableQuantity",
    value: 7,
    unit: "EA",
    deterministic: true,
    confidence: 1,
    source: {
      nodeId: "node.inventory",
      capabilityId: "MM.Inventory.GetAvailability",
      factType: "InventoryAvailability",
    },
    evidence: [{ material: "MAT-1", plant: "P1" }],
    material: "MAT-1",
    plant: "P1",
    asOf: dataAsOf,
    ...overrides,
  };
}

function purchaseOrderFact(overrides: Partial<ReasoningFact> = {}): ReasoningFact {
  return {
    factId: "po-1",
    agentTraceId: "run-1",
    traceId: "trace-po",
    gatewayTraceId: "gateway-po",
    domain: "MM",
    businessObject: "PurchaseOrderItem",
    predicate: "orderQuantity",
    value: 2,
    unit: "EA",
    deterministic: true,
    confidence: 1,
    source: {
      nodeId: "node.po",
      capabilityId: "MM.PurchaseOrder.GetList",
      factType: "PurchaseOrder",
    },
    evidence: [{ purchaseOrder: "4500001", purchaseOrderItem: "10" }],
    material: "MAT-1",
    plant: "P1",
    asOf: dataAsOf,
    ...overrides,
  };
}

function input(
  facts: ReasoningFact[],
  overrides: Partial<ProjectionInput["planExecutionRecord"]> = {},
): ProjectionInput {
  return {
    facts,
    planExecutionRecord: {
      runId: "run-1",
      snapshotId: "snapshot-1",
      asOf: "2026-08-04T00:00:00.000Z",
      nodeLedgerSummary: [
        {
          nodeId: "node.inventory",
          state: "SUCCEEDED",
          nodeExecutedAt: "2026-08-04T00:00:01Z",
        },
        {
          nodeId: "node.po",
          state: "SUCCEEDED",
          nodeExecutedAt: "2026-08-04T00:00:02Z",
        },
      ],
      succeededNodes: ["node.inventory", "node.po"],
      failedNodes: [],
      missingFacts: [],
      ...overrides,
    },
  };
}

describe("materialSupplySnapshotProjection", () => {
  it("declares and registers the exact material supply projection", () => {
    expect(materialSupplySnapshotProjection).toMatchObject({
      projectionId: "material-supply-snapshot",
      version: "1.0.0",
      requiredFactTypes: ["InventoryAvailability"],
      optionalFactTypes: ["PurchaseOrder"],
      outputSchema: "MaterialSupplySnapshot@1.0.0",
      timeBasis: "dataAsOf",
      partialPolicy: "complete-partial-incomplete",
    });
    expect(
      createOutputProjectionRegistry().resolve("material-supply-snapshot", "1.0.0"),
    ).toBe(materialSupplySnapshotProjection);
  });

  it("projects a complete snapshot with per-field lineage and deterministic arrays", () => {
    const facts = [purchaseOrderFact(), inventoryFact()];
    const projectionInput = input(facts, {
      asOf: "2026-08-03T23:30:00.000Z",
    });
    const snapshot = materialSupplySnapshotProjection.project(projectionInput);

    expect(snapshot).toMatchObject({
      projectionId: "material-supply-snapshot",
      projectionVersion: "1.0.0",
      snapshotId: "snapshot-1",
      asOf: "2026-08-03T23:30:00.000Z",
      completeness: "complete",
      missingFacts: [],
      failedNodes: [],
      limitations: [],
      outputHash: computeOutputHash(facts, "1.0.0", "snapshot-1"),
    });
    expect(snapshot.sourceFreshness).toEqual([
      {
        nodeId: "node.inventory",
        nodeExecutedAt: "2026-08-04T00:00:01Z",
        dataAsOf,
      },
      {
        nodeId: "node.po",
        nodeExecutedAt: "2026-08-04T00:00:02Z",
        dataAsOf,
      },
    ]);
    expect(snapshot.lineage).toHaveLength(snapshot.facts.length * 16);
    const expectedFields = [
      "factId",
      "agentTraceId",
      "traceId",
      "gatewayTraceId",
      "domain",
      "businessObject",
      "predicate",
      "value",
      "unit",
      "deterministic",
      "confidence",
      "source",
      "evidence",
      "material",
      "plant",
      "asOf",
    ];
    for (const fact of snapshot.facts) {
      expect(snapshot.lineage.filter((entry) => entry.factId === fact.factId)).toEqual(
        expectedFields.map((field) => ({
          field,
          factId: fact.factId,
          evidence: fact.evidence[0] ?? {},
        })),
      );
    }

    const reversed = materialSupplySnapshotProjection.project({
      facts: [...projectionInput.facts].reverse(),
      planExecutionRecord: {
        ...projectionInput.planExecutionRecord,
        nodeLedgerSummary: [...projectionInput.planExecutionRecord.nodeLedgerSummary].reverse(),
      },
    });
    expect(reversed).toEqual(snapshot);
  });

  it("marks a missing optional fact as partial", () => {
    const snapshot = materialSupplySnapshotProjection.project(input([inventoryFact()]));

    expect(snapshot.completeness).toBe("partial");
    expect(snapshot.missingFacts).toContainEqual({
      factType: "PurchaseOrder",
      reason: "missing_optional",
    });
    expect(snapshot.limitations).toContainEqual(expect.objectContaining({
      kind: "missing_optional",
    }));
  });

  it("marks a missing required fact or terminal failure as incomplete", () => {
    const snapshot = materialSupplySnapshotProjection.project(input([purchaseOrderFact()], {
      nodeLedgerSummary: [
        { nodeId: "node.blocked", state: "BLOCKED_DEPENDENCY" },
        { nodeId: "node.cancelled", state: "CANCELLED" },
        { nodeId: "node.failed", state: "FAILED" },
        { nodeId: "node.timed-out", state: "TIMED_OUT" },
      ],
      failedNodes: ["node.blocked", "node.failed"],
    }));

    expect(snapshot.completeness).toBe("incomplete");
    expect(snapshot.missingFacts).toContainEqual({
      factType: "InventoryAvailability",
      reason: "missing_required",
    });
    expect(snapshot.failedNodes).toEqual([
      "node.cancelled",
      "node.failed",
      "node.timed-out",
    ]);
  });

  it("preserves per-node freshness and reports distinct dataAsOf values", () => {
    const snapshot = materialSupplySnapshotProjection.project(input([
      inventoryFact({ asOf: "2026-08-04T00:30:00+01:00" }),
      purchaseOrderFact({ asOf: "2026-08-04T00:00:00Z" }),
    ], {
      asOf: "2026-08-03T23:30:00.000Z",
    }));

    expect(snapshot.asOf).toBe("2026-08-03T23:30:00.000Z");
    expect(snapshot.sourceFreshness).toEqual([
      {
        nodeId: "node.inventory",
        nodeExecutedAt: "2026-08-04T00:00:01Z",
        dataAsOf: "2026-08-04T00:30:00+01:00",
      },
      {
        nodeId: "node.po",
        nodeExecutedAt: "2026-08-04T00:00:02Z",
        dataAsOf: "2026-08-04T00:00:00Z",
      },
    ]);
    expect(snapshot.limitations).toContainEqual(expect.objectContaining({
      kind: "freshness_mismatch",
    }));
    expect(snapshot.completeness).toBe("partial");
  });

  it("reports required unit incompatibility as incomplete", () => {
    const snapshot = materialSupplySnapshotProjection.project(input([
      inventoryFact({ factId: "inventory-ea", unit: "EA" }),
      inventoryFact({ factId: "inventory-kg", unit: "KG" }),
      purchaseOrderFact(),
    ]));

    expect(snapshot.facts.map((fact) => fact.factId)).toEqual([
      "inventory-ea",
      "inventory-kg",
      "po-1",
    ]);
    expect(snapshot.limitations).toContainEqual(expect.objectContaining({
      kind: "unit_incompatibility",
    }));
    expect(snapshot.completeness).toBe("incomplete");
  });

  it("deduplicates equal facts by the smallest factId without a limitation", () => {
    const projectionInput = input([
      inventoryFact({ factId: "inventory-z" }),
      inventoryFact({ factId: "inventory-a" }),
      purchaseOrderFact(),
    ]);
    const snapshot = materialSupplySnapshotProjection.project(projectionInput);

    expect(snapshot.facts.map((fact) => fact.factId)).toEqual(["inventory-a", "po-1"]);
    expect(snapshot.completeness).toBe("complete");
    expect(snapshot.limitations).toEqual([]);
    expect(materialSupplySnapshotProjection.project({
      ...projectionInput,
      facts: [...projectionInput.facts].reverse(),
    })).toEqual(snapshot);
  });

  it("retains conflicting facts in stable order and blocks a required conflict", () => {
    const snapshot = materialSupplySnapshotProjection.project(input([
      inventoryFact({ factId: "inventory-z", value: 8 }),
      inventoryFact({ factId: "inventory-a", value: 7 }),
      purchaseOrderFact(),
    ]));

    expect(snapshot.facts.slice(0, 2)).toEqual([
      expect.objectContaining({ factId: "inventory-a", conflict: true }),
      expect.objectContaining({ factId: "inventory-z", conflict: true }),
    ]);
    expect(snapshot.limitations).toContainEqual(expect.objectContaining({ kind: "conflict" }));
    expect(snapshot.completeness).toBe("incomplete");
    expect(snapshot.lineage.filter((entry) => entry.field === "conflict")).toEqual([
      {
        field: "conflict",
        factId: "inventory-a",
        evidence: inventoryFact({ factId: "inventory-a" }).evidence[0],
      },
      {
        field: "conflict",
        factId: "inventory-z",
        evidence: inventoryFact({ factId: "inventory-z" }).evidence[0],
      },
    ]);
  });

  it("surfaces assembler no_fact_builder missing facts as an incomplete limitation", () => {
    const snapshot = materialSupplySnapshotProjection.project(input([purchaseOrderFact()], {
      missingFacts: [{ factType: "InventoryAvailability", reason: "no_fact_builder" }],
    }));

    expect(snapshot.missingFacts).toEqual([
      { factType: "InventoryAvailability", reason: "missing_required" },
      { factType: "InventoryAvailability", reason: "no_fact_builder" },
    ]);
    expect(snapshot.limitations).toContainEqual(expect.objectContaining({
      kind: "no_fact_builder",
    }));
    expect(snapshot.completeness).toBe("incomplete");
  });
});
