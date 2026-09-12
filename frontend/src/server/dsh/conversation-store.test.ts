import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { dshConversationStore } from "./conversation-store";

const tmp = mkdtempSync(path.join(tmpdir(), "dsh-store-"));

beforeAll(() => {
  process.env.WORKBENCH_DATA_DIR = tmp;
});

afterAll(() => {
  rmSync(tmp, { recursive: true, force: true });
});

describe("dshConversationStore", () => {
  it("persists a turn and lists it newest-first", async () => {
    await dshConversationStore.addTurn({
      conversationId: "conv-a",
      userText: "查库存",
      assistantText: "可用 10 EA",
      assistantToolCalls: [{ callId: "c1", name: "diagnose_material_supply", status: "completed" }],
    });
    await dshConversationStore.addTurn({
      conversationId: "conv-b",
      userText: "第二个会话",
      assistantText: "好的",
    });

    const list = dshConversationStore.list();
    expect(list[0].id).toBe("conv-b");
    const a = list.find((item) => item.id === "conv-a");
    expect(a?.title).toBe("查库存");
    expect(a?.messageCount).toBe(2);
  });

  it("replays a conversation with user then assistant messages", async () => {
    const conversation = dshConversationStore.get("conv-a");
    expect(conversation).not.toBeNull();
    expect(conversation?.messages.map((message) => message.role)).toEqual(["user", "assistant"]);
    expect(conversation?.messages[1].text).toBe("可用 10 EA");
    expect(conversation?.messages[1].toolCalls).toHaveLength(1);
  });

  it("returns null for an unknown conversation", () => {
    expect(dshConversationStore.get("nope")).toBeNull();
  });

  it("deletes a conversation and its messages", async () => {
    expect(await dshConversationStore.remove("conv-a")).toBe(true);
    expect(dshConversationStore.get("conv-a")).toBeNull();
    expect(dshConversationStore.list().map((item) => item.id)).not.toContain("conv-a");
    // Other conversations survive.
    expect(dshConversationStore.get("conv-b")).not.toBeNull();
    // Deleting again reports not found.
    expect(await dshConversationStore.remove("conv-a")).toBe(false);
  });

  it("truncates a long title", async () => {
    const longText = "这是一个非常非常非常非常非常非常非常非常长的第一条问题";
    await dshConversationStore.addTurn({ conversationId: "conv-long", userText: longText, assistantText: "x" });
    const summary = dshConversationStore.list().find((item) => item.id === "conv-long");
    expect(summary?.title.endsWith("…")).toBe(true);
    expect(summary?.title.length).toBeLessThanOrEqual(25);
  });
});
