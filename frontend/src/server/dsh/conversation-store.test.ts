import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
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
      assistantReasoning: "先判断意图为应收未清，再调用客户敞口工具",
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

  it("replays the persisted reasoning trace alongside the answer", () => {
    // conv-b stored an assistantReasoning; conv-a stored none.
    expect(dshConversationStore.get("conv-b")?.messages[1].reasoning)
      .toBe("先判断意图为应收未清，再调用客户敞口工具");
    expect(dshConversationStore.get("conv-a")?.messages[1].reasoning).toBeUndefined();
  });

  it("returns null for an unknown conversation", () => {
    expect(dshConversationStore.get("nope")).toBeNull();
  });

  it("stores and merges message feedback, and hides it after un-rating", async () => {
    await dshConversationStore.addTurn({
      conversationId: "conv-fb",
      userText: "反馈测试",
      assistantText: "回答",
    });
    const messageId = dshConversationStore.get("conv-fb")!.messages[1].id;

    await dshConversationStore.setFeedback({ conversationId: "conv-fb", messageId, rating: "up" });
    expect(dshConversationStore.get("conv-fb")?.messages[1].feedback?.rating).toBe("up");

    // Note persists across rating updates that omit it.
    await dshConversationStore.setFeedback({ conversationId: "conv-fb", messageId, rating: "down", note: "事实有误" });
    let feedback = dshConversationStore.get("conv-fb")?.messages[1].feedback;
    expect(feedback?.rating).toBe("down");
    expect(feedback?.note).toBe("事实有误");

    // Un-rating hides the entry; the note survives in storage and reappears
    // when the user rates again.
    await dshConversationStore.setFeedback({ conversationId: "conv-fb", messageId, rating: null });
    expect(dshConversationStore.get("conv-fb")?.messages[1].feedback).toBeUndefined();
    await dshConversationStore.setFeedback({ conversationId: "conv-fb", messageId, rating: "up" });
    feedback = dshConversationStore.get("conv-fb")?.messages[1].feedback;
    expect(feedback?.rating).toBe("up");
    expect(feedback?.note).toBe("事实有误");

    // list() never counts feedback records as messages.
    expect(dshConversationStore.list().find((item) => item.id === "conv-fb")?.messageCount).toBe(2);
  });

  it("forks a conversation prefix without carrying feedback", async () => {
    const forked = await dshConversationStore.forkConversation({
      parentId: "conv-fb",
      throughMessageId: dshConversationStore.get("conv-fb")!.messages[1].id,
      newId: "conv-forked",
    });
    expect(forked).not.toBeNull();
    expect(forked?.messages.map((message) => message.role)).toEqual(["user", "assistant"]);
    expect(forked?.messages[1].feedback).toBeUndefined();
    expect(forked?.title).toContain("分叉");

    expect(await dshConversationStore.forkConversation({
      parentId: "conv-fb",
      throughMessageId: "missing",
      newId: "conv-nope",
    })).toBeNull();
    expect(await dshConversationStore.forkConversation({
      parentId: "conv-missing",
      throughMessageId: "any",
      newId: "conv-nope",
    })).toBeNull();
  });

  it("keeps turn order when two turns land in the same millisecond", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-17T10:00:00Z"));
    try {
      await dshConversationStore.addTurn({ conversationId: "conv-ms", userText: "第一问", assistantText: "第一答" });
      await dshConversationStore.addTurn({ conversationId: "conv-ms", userText: "第二问", assistantText: "第二答" });
    } finally {
      vi.useRealTimers();
    }
    const messages = dshConversationStore.get("conv-ms")!.messages;
    expect(messages.map((message) => message.role)).toEqual(["user", "assistant", "user", "assistant"]);
    expect(messages.map((message) => message.text)).toEqual(["第一问", "第一答", "第二问", "第二答"]);
    // Monotonic ts also keeps message ids unique across same-ms turns.
    expect(new Set(messages.map((message) => message.id)).size).toBe(4);
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
