import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlConversationStore } from "./jsonl-conversation-store";
import type { SessionState } from "./types";

function makeSession(): SessionState {
  return { lastContext: null, lastRunId: "run-1", history: [{ role: "user", content: "hi" }] };
}

describe("JsonlConversationStore", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "conv-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("returns null when session does not exist", async () => {
    const store = new JsonlConversationStore(dir);
    expect(await store.load("c1")).toBeNull();
  });

  it("saves and loads a session", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", makeSession());
    const loaded = await store.load("c1");
    expect(loaded).toEqual({ ...makeSession(), principalId: "local-user-0001" });
  });

  it("recovers across store instances (cross-restart)", async () => {
    await new JsonlConversationStore(dir).save("c1", makeSession());
    const reopened = new JsonlConversationStore(dir);
    expect(await reopened.load("c1")).toEqual({ ...makeSession(), principalId: "local-user-0001" });
  });

  it("overwrites on re-save (compaction-safe advisory layer)", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", makeSession());
    const compacted: SessionState = { lastContext: null, lastRunId: null, history: [] };
    await store.save("c1", compacted);
    expect(await store.load("c1")).toEqual({ ...compacted, principalId: "local-user-0001" });
  });

  it("clears a session", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", makeSession());
    await store.clear("c1");
    expect(await store.load("c1")).toBeNull();
  });

  it("clearAll removes all sessions", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", makeSession());
    await store.save("c2", makeSession());
    await store.clearAll();
    expect(await store.load("c1")).toBeNull();
    expect(await store.load("c2")).toBeNull();
  });
});

describe("JsonlConversationStore principalId", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "conv-principal-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("load backfills principalId to local-user-0001 for legacy sessions", async () => {
    const store = new JsonlConversationStore(dir);
    // write a legacy session without principalId
    const legacyState = { lastContext: null, lastRunId: null, history: [] };
    writeFileSync(path.join(dir, "sessions", "c-legacy.json"), JSON.stringify(legacyState));
    const loaded = await store.load("c-legacy");
    expect(loaded?.principalId).toBe("local-user-0001");
  });

  it("load with principalId returns null on mismatch (fail-closed)", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", { lastContext: null, lastRunId: null, history: [], principalId: "user-a" });
    expect(await store.load("c1", "user-a")).not.toBeNull();
    expect(await store.load("c1", "user-b")).toBeNull();
  });

  it("load with principalId returns session on match", async () => {
    const store = new JsonlConversationStore(dir);
    await store.save("c1", { lastContext: null, lastRunId: null, history: [], principalId: "user-a" });
    const loaded = await store.load("c1", "user-a");
    expect(loaded?.principalId).toBe("user-a");
  });
});
