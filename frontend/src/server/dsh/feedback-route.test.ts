import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { dshConversationStore } from "./conversation-store";
import { POST as feedbackPOST } from "../../../app/api/dsh/conversations/[id]/feedback/route";

const tmp = mkdtempSync(path.join(tmpdir(), "dsh-feedback-route-"));

beforeAll(async () => {
  process.env.WORKBENCH_DATA_DIR = tmp;
  await dshConversationStore.addTurn({
    conversationId: "conv-route",
    userText: "路由测试",
    assistantText: "回答",
  });
});

afterAll(() => {
  rmSync(tmp, { recursive: true, force: true });
});

function context(id: string) {
  return { params: Promise.resolve({ id: encodeURIComponent(id) }) };
}

function post(body: unknown) {
  return new Request("http://localhost/api", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("feedback route", () => {
  it("rejects invalid payloads", async () => {
    expect((await feedbackPOST(post({}), context("conv-route"))).status).toBe(400);
    expect((await feedbackPOST(post({ messageId: "m1", rating: "sideways" }), context("conv-route"))).status).toBe(400);
    expect((await feedbackPOST(post({ messageId: "m1", rating: "up", note: 42 }), context("conv-route"))).status).toBe(400);
  });

  it("persists rating and note", async () => {
    const messageId = dshConversationStore.get("conv-route")!.messages[1].id;
    const response = await feedbackPOST(
      post({ messageId, rating: "down", note: "数字对不上" }),
      context("conv-route"),
    );
    expect(response.status).toBe(200);
    const feedback = dshConversationStore.get("conv-route")?.messages[1].feedback;
    expect(feedback?.rating).toBe("down");
    expect(feedback?.note).toBe("数字对不上");
  });
});
