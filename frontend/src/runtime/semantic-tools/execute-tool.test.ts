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
