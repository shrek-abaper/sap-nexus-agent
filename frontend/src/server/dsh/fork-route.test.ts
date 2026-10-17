import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { DshForkError, type DshRuntime } from "./runtime";

const forkSession = vi.fn(async (_parentId: string, _completedTurns: number, _newId: string) => undefined);

vi.mock("./registry", () => ({
  getDshRuntime: vi.fn(async () => ({
    forkSession,
  }) as unknown as DshRuntime),
}));

import { dshConversationStore } from "./conversation-store";
import { POST as forkPOST } from "../../../app/api/dsh/conversations/[id]/fork/route";

const tmp = mkdtempSync(path.join(tmpdir(), "dsh-fork-route-"));

beforeAll(async () => {
  process.env.WORKBENCH_DATA_DIR = tmp;
  await dshConversationStore.addTurn({
    conversationId: "conv-parent",
    userText: "第一轮问题",
    assistantText: "第一轮回答",
  });
  await dshConversationStore.addTurn({
    conversationId: "conv-parent",
    userText: "第二轮问题",
    assistantText: "第二轮回答",
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

describe("fork route", () => {
  it("validates the request and the branch point", async () => {
    expect((await forkPOST(post({}), context("conv-parent"))).status).toBe(400);
    expect((await forkPOST(post({ throughMessageId: "x" }), context("conv-missing"))).status).toBe(404);
    expect((await forkPOST(post({ throughMessageId: "x" }), context("conv-parent"))).status).toBe(400);
    const userMessageId = dshConversationStore.get("conv-parent")!.messages[0].id;
    const notAssistant = await forkPOST(post({ throughMessageId: userMessageId }), context("conv-parent"));
    expect(notAssistant.status).toBe(400);
    expect(forkSession).not.toHaveBeenCalled();
  });

  it("maps DshForkError to 409 without writing a conversation", async () => {
    forkSession.mockRejectedValueOnce(new DshForkError("PARENT_NOT_LIVE", "父会话不在内存中"));
    const assistantId = dshConversationStore.get("conv-parent")!.messages[1].id;
    const response = await forkPOST(post({ throughMessageId: assistantId }), context("conv-parent"));
    expect(response.status).toBe(409);
    const body = await response.json();
    expect(body.errorType).toBe("PARENT_NOT_LIVE");
    expect(dshConversationStore.list().filter((item) => item.title.includes("分叉"))).toHaveLength(0);
  });

  it("forks the session with the completed-turn count and returns the copy", async () => {
    forkSession.mockClear();
    const assistantId = dshConversationStore.get("conv-parent")!.messages[1].id;
    const response = await forkPOST(post({ throughMessageId: assistantId }), context("conv-parent"));
    expect(response.status).toBe(200);
    expect(forkSession).toHaveBeenCalledTimes(1);
    const [parentId, completedTurns, newId] = forkSession.mock.calls[0];
    expect(parentId).toBe("conv-parent");
    expect(completedTurns).toBe(1);

    const body = await response.json();
    expect(body.id).toBe(newId);
    expect(body.messages).toHaveLength(2);
    expect(body.title).toContain("分叉");
  });
});
