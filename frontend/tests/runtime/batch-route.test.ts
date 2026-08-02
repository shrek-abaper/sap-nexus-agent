import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "../../app/api/agent-runs/[runId]/batch/route";
import {
  createAgentRun,
  resetAgentRunsForTests,
  setAgentRunnerForTests
} from "../../src/runtime/agent-runtime-adapter";
import { PLACEHOLDER_PRINCIPAL } from "../../src/runtime/principal/types";

const pendingBatchOutcome = {
  status: "awaiting_batch_confirm",
  responseText: "将查询 2 个组合，请确认。",
  callPlan: {
    agentTraceId: "agent-batch",
    capabilityId: "MM.Inventory.GetAvailability",
    kind: "Function",
    parameters: { material: "DEMOA2", plant: "5200" },
    validationPolicy: "validate_before_execute",
    createdBy: "agent",
    requiresApproval: false
  },
  combinations: [
    { material: "DEMOA2", plant: "5200" },
    { material: "DEMOA2", plant: "1000" }
  ]
};

function request(body: unknown) {
  return new Request("http://localhost/api/agent-runs/run/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

describe("agent run batch route", () => {
  beforeEach(() => resetAgentRunsForTests());
  afterEach(() => {
    setAgentRunnerForTests(null);
    resetAgentRunsForTests();
  });

  it("confirms a pending server-owned batch and returns runId", async () => {
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingBatchOutcome)
      .mockResolvedValueOnce({
        status: "success",
        responseText: "物料 DEMOA2：在工厂 5200 为 176 EA；在工厂 1000 为 0 EA。"
      });
    setAgentRunnerForTests(runner);
    const run = await createAgentRun({ query: "DEMOA2 在 5200 和 1000 的库存", principal: PLACEHOLDER_PRINCIPAL });

    const response = await POST(request({}), {
      params: Promise.resolve({ runId: run.runId })
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ runId: run.runId });
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("maps missing runs to 404", async () => {
    const missing = await POST(request({}), {
      params: Promise.resolve({ runId: "missing" })
    });
    expect(missing.status).toBe(404);
  });

  it("maps duplicate confirmations to 409", async () => {
    const runner = vi
      .fn()
      .mockResolvedValueOnce(pendingBatchOutcome)
      .mockResolvedValueOnce({ status: "success", responseText: "完成" });
    setAgentRunnerForTests(runner);
    const run = await createAgentRun({ query: "DEMOA2 在 5200 和 1000 的库存", principal: PLACEHOLDER_PRINCIPAL });
    await POST(request({}), { params: Promise.resolve({ runId: run.runId }) });

    const duplicate = await POST(request({}), {
      params: Promise.resolve({ runId: run.runId })
    });
    expect(duplicate.status).toBe(409);
  });
});
