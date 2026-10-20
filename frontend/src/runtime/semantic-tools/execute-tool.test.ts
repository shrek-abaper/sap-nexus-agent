import { describe, expect, it } from "vitest";
import { executeSemanticTool } from "./execute-tool";
import { PLACEHOLDER_PRINCIPAL } from "../principal/types";
import type { AgentRunEvent } from "../run-event-schema";

const awaitingEvents: AgentRunEvent[] = [
  { runId: "run-pr", sequence: 0, timestamp: "t", type: "run_started", state: "running" },
  {
    runId: "run-pr", sequence: 1, timestamp: "t", type: "action_proposed", state: "running",
    artifact: {
      label: "proposal", kind: "action-proposal",
      payload: { ref: "proposal-1", snapshotId: "s1", data: {} },
    },
    objectRefs: [{ kind: "proposal", ref: "proposal-1" }],
  },
  { runId: "run-pr", sequence: 2, timestamp: "t", type: "run_completed", state: "awaiting_approval" },
];

const approvalRecord = {
  approvalId: "appr-123",
  runId: "run-pr",
  expiresAt: "2026-09-20T10:00:00.000Z",
  capabilityId: "MM.PR.CreateDraft",
  parameters: {
    material: "DEMOA1", plant: "1000", quantity: "3",
    unit: "EA", delivery_date: "2026-09-25", purchasing_group: "601",
  },
  parameterSources: {},
  factRefs: ["fact:1"],
  subjectHash: "sha256:subj",
  proposalHash: "sha256:prop",
  parameterSnapshotHash: "sha256:params",
};

describe("executeSemanticTool WRITE branch", () => {
  it("returns an approval handle when the governed run awaits approval", async () => {
    const response = await executeSemanticTool({
      contractVersion: 2,
      tool: "propose_replenishment",
      utterance: "补 3 个",
      slots: {
        material: "DEMOA1", plant: "1000",
        requiredQuantity: 10, targetDate: "2026-09-25", purchasingGroup: "601",
      },
    }, PLACEHOLDER_PRINCIPAL, {
      timeoutMs: 1000,
      createRun: async () => ({ runId: "run-pr", turnId: "turn-1" }),
      getEvents: async () => awaitingEvents,
      getRecord: async () => ({
        runId: "run-pr", query: "", events: awaitingEvents, principalId: PLACEHOLDER_PRINCIPAL.principalId,
        pendingOutcome: {
          status: "awaiting_approval",
          responseText: "",
          approvalRecord,
        },
      }),
    });

    expect(response.status).toBe("awaiting_approval");
    expect(response.approval).toMatchObject({
      approvalId: "appr-123",
      runId: "run-pr",
      capabilityId: "MM.PR.CreateDraft",
    });
    expect(response.approval?.parameters).toMatchObject({ material: "DEMOA1", quantity: "3" });
    expect(response.approval?.hashes).toMatchObject({
      subjectHash: "sha256:subj",
      proposalHash: "sha256:prop",
      parameterSnapshotHash: "sha256:params",
    });
  });

  it("falls back to the governed run id when the approval record omits it", async () => {
    // Production python-built approval records carry no TS run id; the card
    // posts to /api/agent-runs/{runId}/approval, so the handle must not be empty.
    const recordWithoutRunId = { ...approvalRecord };
    delete (recordWithoutRunId as { runId?: string }).runId;

    const response = await executeSemanticTool({
      contractVersion: 2,
      tool: "propose_replenishment",
      utterance: "补 3 个",
      slots: {
        material: "DEMOA1", plant: "1000",
        requiredQuantity: 10, targetDate: "2026-09-25", purchasingGroup: "601",
      },
    }, PLACEHOLDER_PRINCIPAL, {
      timeoutMs: 1000,
      createRun: async () => ({ runId: "run-pr", turnId: "turn-1" }),
      getEvents: async () => awaitingEvents,
      getRecord: async () => ({
        runId: "run-pr", query: "", events: awaitingEvents, principalId: PLACEHOLDER_PRINCIPAL.principalId,
        pendingOutcome: { status: "awaiting_approval", responseText: "", approvalRecord: recordWithoutRunId },
      }),
    });

    expect(response.approval?.runId).toBe("run-pr");
  });

  it("rejects replenishment without required constraint slots", async () => {
    await expect(executeSemanticTool({
      contractVersion: 2,
      tool: "propose_replenishment",
      utterance: "补货",
      slots: { material: "DEMOA1", plant: "1000" },
    }, PLACEHOLDER_PRINCIPAL)).rejects.toThrow(/requiredQuantity/);
  });
});


describe("executeSemanticTool entity choice", () => {
  const clarifyEvents: AgentRunEvent[] = [
    { runId: "run-er", sequence: 0, timestamp: "t", type: "run_started", state: "running" },
    {
      runId: "run-er", sequence: 1, timestamp: "t", type: "narrative_created", state: "running",
      artifact: {
        label: "narrated", kind: "narrative",
        payload: { ref: "narrative:x", snapshotId: "s1", data: { text: "找到 2 个可能的匹配" } },
      },
    },
    { runId: "run-er", sequence: 2, timestamp: "t", type: "run_completed", state: "completed" },
  ];

  const entityChoiceForEvent = {
    candidateSetId: "ecs-1",
    objectType: "sapnexus:Material",
    targetCapabilityId: "MM.Inventory.GetAvailability",
    targetSlot: "material",
    mention: "蓝色耐高温密封圈",
    candidates: [{
      index: 1, canonicalCode: "DEMOA1", displayName: "蓝色耐高温密封圈 Ø20",
      distinguishing: { sizeDimension: "20mm" }, matchKind: "substring",
      status: "active", orgScopes: [{ field: "plant", value: "1000" }],
    }],
    snapshotId: "snap-1",
    provider: "PG_MASTERDATA_READ",
    createdAt: "2026-10-20T00:00:00Z",
    expiresAt: "2026-10-20T00:15:00Z",
    principalId: PLACEHOLDER_PRINCIPAL.principalId,
    registrySnapshotId: "sha256:abc",
    sourceExtractedAt: "2026-10-01T00:00:00Z",
  };

  const clarifyEventsWithChoice: AgentRunEvent[] = [
    clarifyEvents[0],
    {
      runId: "run-er", sequence: 1, timestamp: "t", type: "entity_choice_created", state: "narrated",
      artifact: {
        label: "EntityChoiceSet", kind: "entity-choice",
        payload: { ref: "ecs:1", snapshotId: "s1", data: entityChoiceForEvent },
      },
    },
    clarifyEvents[1],
    clarifyEvents[2],
  ];

  it("surfaces the pending entity choice on clarification responses", async () => {
    const response = await executeSemanticTool({
      contractVersion: 2,
      tool: "diagnose_material_supply",
      utterance: "查一下蓝色耐高温密封圈在 1000 工厂的库存",
    }, PLACEHOLDER_PRINCIPAL, {
      timeoutMs: 1000,
      createRun: async () => ({ runId: "run-er", turnId: "turn-1" }),
      getEvents: async () => clarifyEventsWithChoice,
    });

    expect(response.status).toBe("clarification");
    expect(response.entityChoice?.candidateSetId).toBe("ecs-1");
    expect(response.entityChoice?.candidates[0]?.canonicalCode).toBe("DEMOA1");
  });

  it("omits entityChoice when the run has no entity pending", async () => {
    const response = await executeSemanticTool({
      contractVersion: 2,
      tool: "diagnose_material_supply",
      utterance: "库存",
    }, PLACEHOLDER_PRINCIPAL, {
      timeoutMs: 1000,
      createRun: async () => ({ runId: "run-er", turnId: "turn-1" }),
      getEvents: async () => clarifyEvents,
    });

    expect(response.status).toBe("clarification");
    expect(response.entityChoice).toBeUndefined();
  });
});
