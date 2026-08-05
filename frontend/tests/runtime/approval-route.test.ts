import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "../../app/api/agent-runs/[runId]/approval/route";
import {
  createAgentRun,
  getAgentRunEvents,
  resetAgentRunsForTests,
  setAgentRunnerForTests
} from "../../src/runtime/agent-runtime-adapter";
import { PLACEHOLDER_PRINCIPAL } from "../../src/runtime/principal/types";

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

async function waitForApproval(runId: string) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    if (events.some((event) => event.hitlState === "awaiting_human_approval")) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(`Run ${runId} did not reach awaiting_human_approval`);
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
    const run = await createAgentRun({ query: "创建采购申请", principal: PLACEHOLDER_PRINCIPAL });
    await waitForApproval(run.runId);

    const response = await POST(request({ approvalId: "appr-pr", decision: "reject" }), {
      params: Promise.resolve({ runId: run.runId })
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ runId: run.runId });
  });

  it("rejects browser attempts to override approval context", async () => {
    const runner = vi.fn().mockResolvedValueOnce(pendingOutcome);
    setAgentRunnerForTests(runner);
    const run = await createAgentRun({ query: "创建采购申请", principal: PLACEHOLDER_PRINCIPAL });
    await waitForApproval(run.runId);

    const response = await POST(request({
      approvalId: "appr-pr",
      decision: "approve",
      parameters: { quantity: "999" },
      parameterSnapshotHash: "sha256:forged"
    }), { params: Promise.resolve({ runId: run.runId }) });

    expect(response.status).toBe(400);
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("requires the exact server-owned approval identity", async () => {
    const runner = vi.fn().mockResolvedValueOnce(pendingOutcome);
    setAgentRunnerForTests(runner);
    const run = await createAgentRun({ query: "创建采购申请", principal: PLACEHOLDER_PRINCIPAL });
    await waitForApproval(run.runId);

    const missing = await POST(request({ decision: "approve" }), {
      params: Promise.resolve({ runId: run.runId })
    });
    const mismatched = await POST(request({ approvalId: "appr-forged", decision: "approve" }), {
      params: Promise.resolve({ runId: run.runId })
    });

    expect(missing.status).toBe(400);
    expect(mismatched.status).toBe(400);
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("maps missing runs to 404 and completed duplicate decisions to idempotent success", async () => {
    const missing = await POST(request({ approvalId: "appr-pr", decision: "approve" }), {
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
    const run = await createAgentRun({ query: "创建采购申请", principal: PLACEHOLDER_PRINCIPAL });
    await waitForApproval(run.runId);
    await POST(request({ approvalId: "appr-pr", decision: "reject" }), {
      params: Promise.resolve({ runId: run.runId })
    });

    const duplicate = await POST(request({ approvalId: "appr-pr", decision: "reject" }), {
      params: Promise.resolve({ runId: run.runId })
    });
    expect(duplicate.status).toBe(200);
  });
});
