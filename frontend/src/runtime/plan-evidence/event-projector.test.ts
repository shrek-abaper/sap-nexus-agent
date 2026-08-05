import { describe, expect, it } from "vitest";
import {
  PlanEvidenceContractError,
  projectPlanEvidenceEvents,
  type PlanEvidenceBundle,
} from "./event-projector";

function completeBundle(): PlanEvidenceBundle {
  return {
    runId: "run-plan-1",
    traceId: "trace-plan-1",
    snapshotId: "snapshot-1",
    startSequence: 4,
    objects: [
      object("narrative-1", "narrative", { summary: "供应快照完整。" }, ["fact-1", "projection-1"]),
      object("projection-1", "projection", { completeness: "complete", limitations: [] }, ["fact-1"]),
      object("fact-1", "fact", { factTypeId: "InventoryAvailability", value: 12 }),
      object("node-1", "node", { nodeId: "inventory", state: "SUCCEEDED", attempt: 1 }),
      object("plan-1", "plan", { nodes: ["inventory"], topologicalOrder: ["inventory"] }),
      object("capability-1", "capability", { capabilityId: "MM.Inventory.GetAvailability" }),
      object("intent-1", "intent", { goal: "查询供给" }),
      object("recommendation-1", "recommendation", { status: "NO_ACTION" }, ["projection-1"]),
    ],
  };
}

function object(
  ref: string,
  kind: PlanEvidenceBundle["objects"][number]["kind"],
  payload: PlanEvidenceBundle["objects"][number]["payload"],
  evidenceRefs: string[] = [],
): PlanEvidenceBundle["objects"][number] {
  return { ref, kind, snapshotId: "snapshot-1", payload, evidenceRefs };
}

describe("projectPlanEvidenceEvents", () => {
  it("emits the governed event family in stable stage order with one envelope", () => {
    const events = projectPlanEvidenceEvents(completeBundle());

    expect(events.map((event) => event.type)).toEqual([
      "intent_recognized",
      "capability_recalled",
      "plan_compiled",
      "plan_node_state",
      "fact_emitted",
      "projection_completed",
      "recommendation_completed",
      "narrative_completed",
    ]);
    expect(events.map((event) => event.sequence)).toEqual([4, 5, 6, 7, 8, 9, 10, 11]);
    expect(events.every((event) => event.runId === "run-plan-1")).toBe(true);
    expect(events.every((event) => event.traceId === "trace-plan-1")).toBe(true);
    expect(events.every((event) => event.snapshotId === "snapshot-1")).toBe(true);
    expect(events.every((event) => event.objectRefs?.length === 1)).toBe(true);
  });

  it("rejects objects and evidence references outside the bundle snapshot", () => {
    const bundle = completeBundle();
    bundle.objects[0] = { ...bundle.objects[0], snapshotId: "snapshot-other" };

    expect(() => projectPlanEvidenceEvents(bundle)).toThrowError(
      expect.objectContaining<Partial<PlanEvidenceContractError>>({ code: "CROSS_SNAPSHOT_REFERENCE" }),
    );
  });

  it("rejects an unknown NarrativeEnvelope claim reference before projection", () => {
    const bundle = completeBundle();
    bundle.objects[0] = object(
      "narrative-1",
      "narrative",
      {
        summary: "供应快照完整。",
        claims: [{ claimId: "claim-1", text: "无来源结论", evidenceRefs: ["fact-missing"] }],
      },
      ["fact-1", "projection-1"],
    );

    expect(() => projectPlanEvidenceEvents(bundle)).toThrowError(
      expect.objectContaining<Partial<PlanEvidenceContractError>>({ code: "UNKNOWN_OBJECT_REFERENCE" }),
    );
  });

  it("rejects technical execution fields before they can enter durable events", () => {
    const bundle = completeBundle();
    bundle.objects[2] = object("fact-1", "fact", {
      factTypeId: "InventoryAvailability",
      rfcName: "BAPI_MATERIAL_STOCK_REQ_LIST",
    });

    expect(() => projectPlanEvidenceEvents(bundle)).toThrowError(
      expect.objectContaining<Partial<PlanEvidenceContractError>>({ code: "UNSAFE_FIELD" }),
    );
  });

  it("rejects fields outside the governed object allowlist", () => {
    const bundle = completeBundle();
    bundle.objects[2] = object("fact-1", "fact", {
      factTypeId: "InventoryAvailability",
      value: 12,
      diagnosticBlob: "not governed",
    });

    expect(() => projectPlanEvidenceEvents(bundle)).toThrowError(
      expect.objectContaining<Partial<PlanEvidenceContractError>>({ code: "UNSUPPORTED_FIELD" }),
    );
  });

  it("redacts credential-like fields nested inside an allowed safe summary", () => {
    const bundle = completeBundle();
    bundle.objects[3] = object("node-1", "node", {
      nodeId: "inventory",
      state: "SUCCEEDED",
      attempt: 1,
      safeResult: { status: "succeeded", token: "secret-runtime-token" },
    });

    const serialized = JSON.stringify(projectPlanEvidenceEvents(bundle));
    expect(serialized).toContain("[REDACTED]");
    expect(serialized).not.toContain("secret-runtime-token");
  });

  it("keeps a pending ActionProposal read-only and does not invent approval events", () => {
    const bundle = completeBundle();
    bundle.objects.push(
      object(
        "proposal-1",
        "proposal",
        {
          capabilityId: "MM.PR.CreateDraft",
          status: "pending_approval",
          proposalHash: "proposal-hash-1",
          parameterSources: { quantity: "rule:shortage" },
        },
        ["fact-1", "recommendation-1"],
      ),
    );

    const events = projectPlanEvidenceEvents(bundle);
    const proposal = events.find((event) => event.type === "action_proposed");

    expect(proposal?.artifact?.kind).toBe("action-proposal");
    expect(proposal?.state).toBe("running");
    expect(events.some((event) => event.type === "approval_updated")).toBe(false);
    expect(events.some((event) => event.type === "action_executed")).toBe(false);
  });
});
