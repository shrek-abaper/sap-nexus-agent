import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "../../app/api/agent-runs/[runId]/approval/route";
import {
  createAgentRun,
  resetAgentRunsForTests,
  setAgentRunnerForTests
} from "../../src/runtime/agent-runtime-adapter";

const pendingOutcome = {
  status: "awaiting_approval",
  callPlan: {
    agentTraceId: "agent-pr",
    capabilityId: "MM.PR.CreateDraft",
    kind: "Action",
    parameters: { material: "M001", plant: "1000" },
    validationPolicy: "validate_before_execute",
    createdBy: "agent",
    requiresApproval: true
  },
  validationResult: {
    traceId: "gw-validate-pr",
    capabilityId: "MM.PR.CreateDraft",
    success: true,
    errorType: "NONE",
    messages: []
  },
  approvalRecord: {
    approvalId: "appr-pr",
    capabilityId: "MM.PR.CreateDraft",
    parameterSnapshotHash: "sha256:approved",
    parameters: { material: "M001", plant: "1000" },
    approver: "user",
    approvedAt: "2026-07-17T10:00:00Z",
    expiresAt: "2026-07-17T10:10:00Z",
    status: "pending"
  }
};

function request(body: unknown) {
  return new Request("http://localhost/api/agent-runs/run/approval", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

describe("agent run approval route", () => {
  beforeEach(() => resetAgentRunsForTests());
  afterEach(() => {
    setAgentRunnerForTests(null);
    resetAgentRunsForTests();
  });

  it("accepts a decision for a pending server-owned Action", async () => {
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingOutcome)
      .mockResolvedValueOnce({
        status: "rejected",
        callPlan: pendingOutcome.callPlan,
        validationResult: pendingOutcome.validationResult,
        approvalRecord: { ...pendingOutcome.approvalRecord, status: "rejected" }
      });
    setAgentRunnerForTests(runner);
    const run = await createAgentRun({ query: "创建采购申请" });

    const response = await POST(request({ decision: "reject" }), {
      params: Promise.resolve({ runId: run.runId })
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ runId: run.runId });
  });

  it("rejects browser attempts to override approval context", async () => {
    const runner = vi.fn().mockResolvedValueOnce(pendingOutcome);
    setAgentRunnerForTests(runner);
    const run = await createAgentRun({ query: "创建采购申请" });

    const response = await POST(request({
      decision: "approve",
      parameters: { quantity: "999" },
      parameterSnapshotHash: "sha256:forged"
    }), { params: Promise.resolve({ runId: run.runId }) });

    expect(response.status).toBe(400);
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("maps missing runs and duplicate decisions to 404 and 409", async () => {
    const missing = await POST(request({ decision: "approve" }), {
      params: Promise.resolve({ runId: "missing" })
    });
    expect(missing.status).toBe(404);

    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingOutcome)
      .mockResolvedValueOnce({
        status: "rejected",
        callPlan: pendingOutcome.callPlan,
        validationResult: pendingOutcome.validationResult,
        approvalRecord: { ...pendingOutcome.approvalRecord, status: "rejected" }
      });
    setAgentRunnerForTests(runner);
    const run = await createAgentRun({ query: "创建采购申请" });
    await POST(request({ decision: "reject" }), {
      params: Promise.resolve({ runId: run.runId })
    });

    const duplicate = await POST(request({ decision: "reject" }), {
      params: Promise.resolve({ runId: run.runId })
    });
    expect(duplicate.status).toBe(409);
  });
});
