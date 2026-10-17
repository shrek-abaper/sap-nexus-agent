import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { DshRuntime, DshStreamEvent } from "./runtime";

vi.mock("./registry", () => ({
  getDshRuntime: vi.fn(async () => ({
    streamMessage: vi.fn(async function* (): AsyncGenerator<DshStreamEvent> {
      yield { type: "delta", text: "思考", phase: "reasoning" };
      yield { type: "final", output: "最终回答", toolCalls: [] };
    }),
  }) as unknown as DshRuntime),
  dshModelConfigured: vi.fn(() => true),
}));

import { dshConversationStore } from "./conversation-store";
import { POST as streamPOST } from "../../../app/api/dsh/conversations/[id]/messages/stream/route";

const tmp = mkdtempSync(path.join(tmpdir(), "dsh-stream-route-"));

beforeAll(() => {
  process.env.WORKBENCH_DATA_DIR = tmp;
});

afterAll(() => {
  rmSync(tmp, { recursive: true, force: true });
});

describe("message stream route", () => {
  it("emits the persisted store message ids after the final event", async () => {
    const response = await streamPOST(
      new Request("http://localhost/api", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: "测试问题" }),
      }),
      { params: Promise.resolve({ id: "conv-stream" }) },
    );
    const body = await response.text();
    const events = body
      .split("\n\n")
      .filter((chunk) => chunk.startsWith("data:"))
      .map((chunk) => JSON.parse(chunk.slice(5).trim()) as { type: string });

    expect(events.map((event) => event.type)).toEqual(["delta", "final", "persisted"]);
    const persisted = events[2] as unknown as { userMessageId: string; assistantMessageId: string };
    const stored = dshConversationStore.get("conv-stream")!;
    expect(stored.messages[0].id).toBe(persisted.userMessageId);
    expect(stored.messages[1].id).toBe(persisted.assistantMessageId);
  });
});
