import { describe, expect, it } from "vitest";
import type { WorkbenchOutcome } from "../durable/types";
import { CompositionHandoffError, parseCompositionHandoff } from "./handoff";

const planGraph = {
  planGraphVersion: 2,
  planId: "plan-1",
  goalId: "goal-1",
  executionMode: "read",
  snapshotId: "snapshot-1",
  nodes: [{
    nodeId: "inventory",
    capabilityId: "MM.Inventory.GetAvailability",
    parameterBindings: [
      { parameterName: "material", source: { kind: "literal", semanticType: "MaterialId", value: "MAT-1" } },
      { parameterName: "plant", source: { kind: "literal", semanticType: "PlantId", value: "P1" } },
    ],
    producesFactTypes: ["InventoryAvailability"],
    governance: { requiresApproval: false },
  }],
  edges: [],
  topologicalOrder: ["inventory"],
  goalOutputs: [{ factTypeId: "InventoryAvailability", producerNodeId: "inventory" }],
  readPartition: ["inventory"],
  actionPartition: [],
  projectionRef: [],
  ruleSetRefs: [],
};

function escalation(overrides: Partial<WorkbenchOutcome> = {}): WorkbenchOutcome {
  return {
    status: "match_decision",
    matchDecision: {
      decisionType: "ESCALATE_TO_PLANNER",
      handoff: { registrySnapshotId: "snapshot-1" },
    },
    dryRun: { planGraph, gaps: [], governanceFlags: [] },
    ...overrides,
  };
}

describe("parseCompositionHandoff", () => {
  it("accepts only a gap-free PlanGraph bound to the semantic handoff snapshot", () => {
    expect(parseCompositionHandoff(escalation())).toEqual({
      graph: planGraph,
      snapshotId: "snapshot-1",
    });
  });

  it("keeps non-escalation outcomes on the existing single-capability path", () => {
    expect(parseCompositionHandoff({
      status: "success",
      matchDecision: { decisionType: "SELECT" },
    })).toBeNull();
  });

  it("fails closed before Gateway when the authored plan drifts snapshots", () => {
    expect(() => parseCompositionHandoff(escalation({
      dryRun: { planGraph: { ...planGraph, snapshotId: "snapshot-2" }, gaps: [], governanceFlags: [] },
    }))).toThrowError(expect.objectContaining<Partial<CompositionHandoffError>>({
      errorType: "COMPOSITION_SNAPSHOT_MISMATCH",
    }));
  });

  it("fails closed when the planner reports a blocking gap", () => {
    expect(() => parseCompositionHandoff(escalation({
      dryRun: {
        planGraph,
        gaps: [{ kind: "missing_parameter", detail: "plant" }],
        governanceFlags: [],
      },
    }))).toThrowError(expect.objectContaining<Partial<CompositionHandoffError>>({
      errorType: "COMPOSITION_PLAN_GAPS",
    }));
  });
});
