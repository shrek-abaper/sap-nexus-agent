import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./registry", () => ({
  getDshRuntime: vi.fn(async () => runtime),
  dshModelConfigured: vi.fn(() => true),
}));

import { POST } from "../../../app/api/dsh/conversations/[id]/messages/route";
import type { DshRuntime } from "./runtime";

let runtime: DshRuntime;

function setRuntime(turn: Awaited<ReturnType<DshRuntime["sendMessage"]>>): void {
  runtime = { sendMessage: vi.fn(async () => turn), streamMessage: vi.fn(async function* () {}), dispose: vi.fn() };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("POST /api/dsh/conversations/:id/messages", () => {
  it("returns assistant text and structured tool calls", async () => {
    setRuntime({
      output: "A100 可用 12 EA",
      reasonKind: "completed",
      toolCalls: [{
        callId: "c1",
        name: "diagnose_material_supply",
        args: { utterance: "x" },
        status: "completed",
        result: {
          status: "complete",
          runId: "run-1",
          contractVersion: 2,
          tool: "diagnose_material_supply",
          resolved: { semanticValues: [] },
          capabilityChain: [{ capabilityId: "MM.Inventory.GetAvailability", state: "succeeded" }],
          facts: [],
          narrative: { summary: "12 EA", limitations: [] },
          limitations: [],
        },
      }],
    });

    const response = await POST(
      new Request("http://localhost/api/dsh/conversations/conv-1/messages", {
        method: "POST",
        body: JSON.stringify({ text: "A100 够不够" }),
      }),
      { params: Promise.resolve({ id: "conv-1" }) },
    );
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({ conversationId: "conv-1", output: "A100 可用 12 EA" });
    expect(body.toolCalls[0].name).toBe("diagnose_material_supply");
    expect(runtime.sendMessage).toHaveBeenCalledWith("conv-1", "A100 够不够");
  });

  it("rejects empty text with 400", async () => {
    setRuntime({ output: "", toolCalls: [] });
    const response = await POST(
      new Request("http://localhost/x", { method: "POST", body: JSON.stringify({ text: "  " }) }),
      { params: Promise.resolve({ id: "conv-1" }) },
    );
    expect(response.status).toBe(400);
  });

});
