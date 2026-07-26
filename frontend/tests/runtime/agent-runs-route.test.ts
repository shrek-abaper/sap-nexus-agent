import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "../../app/api/agent-runs/route";
import {
  resetAgentRunsForTests,
  resetAgentSessionsForTests,
  setAgentRunnerForTests
} from "../../src/runtime/agent-runtime-adapter";

function request(body: unknown) {
  return new Request("http://localhost/api/agent-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

describe("agent run creation route", () => {
  beforeEach(() => {
    resetAgentRunsForTests();
    resetAgentSessionsForTests();
  });
  afterEach(() => {
    setAgentRunnerForTests(null);
    resetAgentRunsForTests();
    resetAgentSessionsForTests();
  });

  it("forwards conversationId so multi-turn session context is preserved across requests", async () => {
    // The route must forward the browser-supplied conversationId to
    // createAgentRun. Without it the adapter cannot key the session, so the
    // second request on the same conversation loses the prior lastContext
    // and multi-turn continuity silently breaks.
    const runner = vi.fn(async (_input: any) => ({
      status: "clarification",
      responseText: "请提供工厂。",
      lastContext: {
        capabilityId: "MM.Inventory.GetAvailability",
        parameters: { material: "DEMOA2" },
        missingParameters: ["plant"],
        decisionType: "CLARIFY" as const
      }
    }));
    setAgentRunnerForTests(runner);

    const first = await POST(request({ query: "查库存 DEMOA2", conversationId: "conv-route-1" }));
    expect(first.status).toBe(200);

    // Second request on the SAME conversationId must inherit the prior
    // lastContext. This only holds if the route forwarded conversationId
    // to createAgentRun; otherwise the adapter passes context=undefined.
    const second = await POST(request({ query: "1000", conversationId: "conv-route-1" }));
    expect(second.status).toBe(200);

    const secondCall = runner.mock.calls[1][0];
    expect(secondCall.context).toBeDefined();
    expect(secondCall.context.lastContext.capabilityId).toBe("MM.Inventory.GetAvailability");
    expect(secondCall.context.lastContext.parameters).toEqual({ material: "DEMOA2" });
  });
});
