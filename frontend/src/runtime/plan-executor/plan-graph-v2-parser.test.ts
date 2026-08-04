import { describe, expect, it } from "vitest";
import { parsePlanGraphV2, validatePlanGraphV2 } from "./plan-graph-v2-parser";

const validPlanGraph = {
  planGraphVersion: 2,
  planId: "plan-001",
  goalId: "goal-001",
  executionMode: "advisory",
  snapshotId: "sha256:abc123",
  nodes: [
    {
      nodeId: "node.mm.inventory.getavailability",
      capabilityId: "MM.Inventory.GetAvailability",
      parameterBindings: [
        { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "DEMOA4B" } },
        { parameterName: "plant", source: { kind: "literal", semanticType: "PlantCode", value: "5300" } },
      ],
      producesFactTypes: ["InventoryAvailability"],
      governance: { requiresApproval: false },
    },
    {
      nodeId: "node.mm.purchaseorder.getlist",
      capabilityId: "MM.PurchaseOrder.GetList",
      parameterBindings: [
        { parameterName: "material", source: { kind: "literal", semanticType: "MaterialCode", value: "DEMOA4B" } },
        { parameterName: "plant", source: { kind: "literal", semanticType: "PlantCode", value: "5300" } },
      ],
      producesFactTypes: ["PurchaseOrder"],
      governance: { requiresApproval: false },
    },
  ],
  edges: [],
  topologicalOrder: ["node.mm.inventory.getavailability", "node.mm.purchaseorder.getlist"],
  goalOutputs: [],
  readPartition: ["node.mm.inventory.getavailability", "node.mm.purchaseorder.getlist"],
  actionPartition: [],
  projectionRef: [],
  ruleSetRefs: [],
};

describe("parsePlanGraphV2", () => {
  it("parses a valid v2 plan_graph with readPartition", () => {
    const result = parsePlanGraphV2(validPlanGraph);
    expect(result).not.toBeNull();
    expect(result!.planGraphVersion).toBe(2);
    expect(result!.readPartition).toEqual(["node.mm.inventory.getavailability", "node.mm.purchaseorder.getlist"]);
    expect(result!.nodes).toHaveLength(2);
    expect(result!.nodes[0].capabilityId).toBe("MM.Inventory.GetAvailability");
  });

  it("returns null for null/undefined input", () => {
    expect(parsePlanGraphV2(null)).toBeNull();
    expect(parsePlanGraphV2(undefined)).toBeNull();
  });

  it("returns null for non-object input", () => {
    expect(parsePlanGraphV2("string")).toBeNull();
    expect(parsePlanGraphV2(42)).toBeNull();
  });

  it("returns null when planGraphVersion !== 2", () => {
    expect(parsePlanGraphV2({ ...validPlanGraph, planGraphVersion: 1 })).toBeNull();
  });

  it("returns null when readPartition is missing", () => {
    const { readPartition: _drop, ...rest } = validPlanGraph;
    expect(parsePlanGraphV2(rest)).toBeNull();
  });
});

describe("validatePlanGraphV2", () => {
  const snapshotId = "sha256:abc123";

  it("validates a correct plan_graph with matching snapshotId", () => {
    const graph = parsePlanGraphV2(validPlanGraph)!;
    const result = validatePlanGraphV2(graph, snapshotId);
    expect(result.valid).toBe(true);
  });

  it("rejects snapshot drift", () => {
    const graph = parsePlanGraphV2(validPlanGraph)!;
    const result = validatePlanGraphV2(graph, "sha256:different");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("snapshot drift");
  });

  it("rejects empty readPartition", () => {
    const graph = parsePlanGraphV2({ ...validPlanGraph, readPartition: [] })!;
    const result = validatePlanGraphV2(graph, snapshotId);
    expect(result.valid).toBe(false);
    expect(result.error).toContain("readPartition is empty");
  });

  it("rejects when readPartition references non-existent node", () => {
    const graph = parsePlanGraphV2({ ...validPlanGraph, readPartition: ["node.does.not.exist"] })!;
    const result = validatePlanGraphV2(graph, snapshotId);
    expect(result.valid).toBe(false);
    expect(result.error).toContain("not found");
  });
});
