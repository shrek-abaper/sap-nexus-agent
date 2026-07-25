import { describe, expect, it } from "vitest";
import { buildDryRunView } from "../../src/modules/agent-console/view-model";
import type { AgentRunSnapshot, AgentRunEvent } from "../../src/runtime/run-event-schema";
import type { JsonValue } from "../../src/shared/types/artifacts";

const baseEvent = {
  runId: "run-dry-run",
  sequence: 1,
  timestamp: "2026-07-25T00:00:00.000Z"
} as const;

function matchDecisionEvent(payload: JsonValue, sequence = 2): AgentRunEvent {
  return {
    ...baseEvent,
    sequence,
    type: "match_decision_created",
    state: "match_decided",
    artifact: {
      label: "MatchDecision",
      kind: "match-decision",
      payload
    }
  };
}

function snapshotWith(events: AgentRunEvent[]): AgentRunSnapshot {
  return {
    runId: "run-dry-run",
    state: events.at(-1)?.state ?? "completed",
    hitlState: "approval_not_required",
    events
  };
}

const dryRunPayload: JsonValue = {
  decisionType: "ESCALATE_TO_PLANNER",
  candidates: null,
  handoff: {
    reason: "multi-intent",
    matchedIntents: [
      {
        capabilityId: "MM.Inventory.GetAvailability",
        parameters: { material: "DEMOA2", plant: "5100" },
        missing: []
      },
      {
        capabilityId: "MM.PurchaseOrder.GetList",
        parameters: {},
        missing: []
      }
    ],
    utterance: "DEMOA2 在 5100 的库存，再列出近 30 天未清采购订单",
    registrySnapshotId: "reg-snap-2026-07-25"
  },
  rationale: "多目标 utterance 命中库存与采购订单能力，需 planner 编排。",
  dryRun: {
    planGraph: {
      planGraphVersion: 1,
      planId: "plan.dry-run.goal-1",
      goalId: "goal-1",
      executionMode: "PLAN_ONLY",
      snapshotId: "reg-snap-2026-07-25",
      nodes: [
        {
          nodeId: "node.MM.Inventory.GetAvailability",
          capabilityId: "MM.Inventory.GetAvailability",
          parameterBindings: [
            {
              parameterName: "material",
              source: { kind: "goalConstraint", constraintName: "material" }
            },
            {
              parameterName: "plant",
              source: { kind: "goalConstraint", constraintName: "plant" }
            }
          ],
          producesFactTypes: ["sapnexus:InventoryAvailabilityFact"],
          governance: {
            capabilityKind: "Function",
            sideEffect: "none",
            requiresApproval: false,
            approvalPolicy: "not_required"
          }
        },
        {
          nodeId: "node.MM.PurchaseOrder.GetList",
          capabilityId: "MM.PurchaseOrder.GetList",
          parameterBindings: [],
          producesFactTypes: ["sapnexus:PurchaseOrderSupplyFact"],
          governance: {
            capabilityKind: "Function",
            sideEffect: "none",
            requiresApproval: false,
            approvalPolicy: "not_required"
          }
        }
      ],
      edges: [],
      topologicalOrder: [
        "node.MM.Inventory.GetAvailability",
        "node.MM.PurchaseOrder.GetList"
      ],
      goalOutputs: [
        {
          factTypeId: "sapnexus:InventoryAvailabilityFact",
          producerNodeId: "node.MM.Inventory.GetAvailability"
        },
        {
          factTypeId: "sapnexus:PurchaseOrderSupplyFact",
          producerNodeId: "node.MM.PurchaseOrder.GetList"
        }
      ]
    },
    gaps: [
      { kind: "missing_parameter", detail: "MM.PurchaseOrder.GetList.poNumber" }
    ],
    governanceFlags: [
      { kind: "approval_required", detail: "MM.PR.CreateDraft" }
    ],
    rationale: "dry-run compiled 2 node(s), 1 gap(s), 1 flag(s)"
  }
};

const dryRunPayloadWithoutDryRun: JsonValue = {
  decisionType: "SHOW_OPTIONS",
  candidates: [
    {
      capabilityId: "MM.Inventory.GetAvailability",
      parameters: { material: "DEMOA2" },
      missing: ["plant"]
    }
  ],
  handoff: null,
  rationale: "ambiguous"
};

describe("buildDryRunView - S2-B dry-run 预览视图", () => {
  it("returns null when snapshot is null", () => {
    expect(buildDryRunView(null)).toBeNull();
  });

  it("returns null when no match-decision artifact is present", () => {
    const snap: AgentRunSnapshot = {
      runId: "run-dry-run",
      state: "completed",
      hitlState: "approval_not_required",
      events: [
        { ...baseEvent, sequence: 1, type: "run_started", state: "running" },
        { ...baseEvent, sequence: 2, type: "narrative_created", state: "narrated" }
      ]
    };
    expect(buildDryRunView(snap)).toBeNull();
  });

  it("returns null when match-decision artifact has no dryRun field", () => {
    const snap = snapshotWith([matchDecisionEvent(dryRunPayloadWithoutDryRun)]);
    expect(buildDryRunView(snap)).toBeNull();
  });

  it("parses planGraph nodes, edges, goalOutputs from dryRun payload", () => {
    const snap = snapshotWith([matchDecisionEvent(dryRunPayload)]);
    const view = buildDryRunView(snap);
    expect(view).not.toBeNull();
    expect(view?.planGraph.planId).toBe("plan.dry-run.goal-1");
    expect(view?.planGraph.goalId).toBe("goal-1");
    expect(view?.planGraph.executionMode).toBe("PLAN_ONLY");
    expect(view?.planGraph.nodes).toHaveLength(2);
    expect(view?.planGraph.nodes[0].capabilityId).toBe("MM.Inventory.GetAvailability");
    expect(view?.planGraph.nodes[0].parameterBindings).toHaveLength(2);
    expect(view?.planGraph.nodes[0].parameterBindings[0].source.kind).toBe(
      "goalConstraint"
    );
    expect(view?.planGraph.nodes[0].producesFactTypes).toEqual([
      "sapnexus:InventoryAvailabilityFact"
    ]);
    expect(view?.planGraph.edges).toEqual([]);
    expect(view?.planGraph.topologicalOrder).toHaveLength(2);
    expect(view?.planGraph.goalOutputs).toHaveLength(2);
  });

  it("parses gaps with kind and detail", () => {
    const snap = snapshotWith([matchDecisionEvent(dryRunPayload)]);
    const view = buildDryRunView(snap);
    expect(view?.gaps).toEqual([
      { kind: "missing_parameter", detail: "MM.PurchaseOrder.GetList.poNumber" }
    ]);
  });

  it("parses governanceFlags with kind and detail", () => {
    const snap = snapshotWith([matchDecisionEvent(dryRunPayload)]);
    const view = buildDryRunView(snap);
    expect(view?.governanceFlags).toEqual([
      { kind: "approval_required", detail: "MM.PR.CreateDraft" }
    ]);
  });

  it("exposes rationale string", () => {
    const snap = snapshotWith([matchDecisionEvent(dryRunPayload)]);
    const view = buildDryRunView(snap);
    expect(view?.rationale).toBe("dry-run compiled 2 node(s), 1 gap(s), 1 flag(s)");
  });

  it("returns null when dryRun payload is malformed (planGraph missing)", () => {
    const malformed: JsonValue = {
      decisionType: "ESCALATE_TO_PLANNER",
      handoff: null,
      rationale: "x",
      dryRun: { gaps: [], governanceFlags: [], rationale: "x" }
    };
    const snap = snapshotWith([matchDecisionEvent(malformed)]);
    expect(buildDryRunView(snap)).toBeNull();
  });

  it("returns null when dryRun is not an object", () => {
    const malformed: JsonValue = {
      decisionType: "ESCALATE_TO_PLANNER",
      handoff: null,
      rationale: "x",
      dryRun: "not-an-object"
    };
    const snap = snapshotWith([matchDecisionEvent(malformed)]);
    expect(buildDryRunView(snap)).toBeNull();
  });

  it("handles missing gaps / governanceFlags defensively (empty arrays)", () => {
    const minimal: JsonValue = {
      decisionType: "ESCALATE_TO_PLANNER",
      handoff: null,
      rationale: "x",
      dryRun: {
        planGraph: {
          planGraphVersion: 1,
          planId: "p",
          goalId: "g",
          executionMode: "PLAN_ONLY",
          snapshotId: "s",
          nodes: [],
          edges: [],
          topologicalOrder: [],
          goalOutputs: []
        },
        rationale: "empty plan"
      }
    };
    const snap = snapshotWith([matchDecisionEvent(minimal)]);
    const view = buildDryRunView(snap);
    expect(view).not.toBeNull();
    expect(view?.gaps).toEqual([]);
    expect(view?.governanceFlags).toEqual([]);
    expect(view?.rationale).toBe("empty plan");
  });

  it("handles node with missing parameterBindings defensively (empty array)", () => {
    const minimal: JsonValue = {
      decisionType: "ESCALATE_TO_PLANNER",
      handoff: null,
      rationale: "x",
      dryRun: {
        planGraph: {
          planGraphVersion: 1,
          planId: "p",
          goalId: "g",
          executionMode: "PLAN_ONLY",
          snapshotId: "s",
          nodes: [
            {
              nodeId: "n1",
              capabilityId: "MM.Inventory.GetAvailability"
              // parameterBindings omitted
            }
          ],
          edges: [],
          topologicalOrder: ["n1"],
          goalOutputs: []
        },
        gaps: [],
        governanceFlags: [],
        rationale: "x"
      }
    };
    const snap = snapshotWith([matchDecisionEvent(minimal)]);
    const view = buildDryRunView(snap);
    expect(view?.planGraph.nodes[0].parameterBindings).toEqual([]);
  });
});
