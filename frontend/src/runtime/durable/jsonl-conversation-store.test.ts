import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlConversationStore } from "./jsonl-conversation-store";
import type { SessionState, SessionStateV2 } from "./types";

const PRINCIPAL = "local-user-0001";

function makeSession(overrides: Partial<SessionStateV2> = {}): SessionStateV2 {
  return {
    schemaVersion: 2,
    stateVersion: 1,
    principalId: PRINCIPAL,
    activeFrame: null,
    recentFrames: [],
    pendingInteraction: null,
    history: [{ role: "user", content: "hi" }],
    lastAppliedTurnId: "turn-1",
    lastRunId: "run-1",
    ...overrides,
  };
}

describe("JsonlConversationStore", () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "conv-v2-"));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    rmSync(dir, { recursive: true, force: true });
  });

  it("returns null when the conversation does not exist", async () => {
    const store = new JsonlConversationStore(dir);
    expect(await store.load("c1", PRINCIPAL)).toBeNull();
  });

  it("saves by CAS and loads the v2 session across store instances", async () => {
    const store = new JsonlConversationStore(dir);
    expect(await store.compareAndSwap("c1", 0, makeSession())).toEqual({
      status: "saved",
      stateVersion: 1,
    });

    const reopened = new JsonlConversationStore(dir);
    expect(await reopened.load("c1", PRINCIPAL)).toEqual(makeSession());
  });

  it("rejects a stale CAS without overwriting the winning state", async () => {
    const store = new JsonlConversationStore(dir);
    await store.compareAndSwap("c1", 0, makeSession());
    const winner = makeSession({ stateVersion: 2, lastAppliedTurnId: "turn-2" });
    expect(await store.compareAndSwap("c1", 1, winner)).toEqual({
      status: "saved",
      stateVersion: 2,
    });

    const stale = makeSession({ stateVersion: 2, lastAppliedTurnId: "stale-turn" });
    expect(await store.compareAndSwap("c1", 1, stale)).toEqual({
      status: "conflict",
      actualVersion: 2,
    });
    expect((await store.load("c1", PRINCIPAL))?.lastAppliedTurnId).toBe("turn-2");
  });

  it("requires the next stateVersion to advance exactly once", async () => {
    const store = new JsonlConversationStore(dir);
    await expect(store.compareAndSwap("c1", 0, makeSession({ stateVersion: 2 })))
      .rejects.toMatchObject({ code: "CONTEXT_INVALID_VERSION_TRANSITION" });
    expect(await store.load("c1", PRINCIPAL)).toBeNull();
  });

  it("rejects a negative expectedVersion instead of creating version zero", async () => {
    const store = new JsonlConversationStore(dir);
    await expect(store.compareAndSwap("c1", -1, makeSession({ stateVersion: 0 })))
      .rejects.toMatchObject({ code: "CONTEXT_INVALID_VERSION_TRANSITION" });
    expect(await store.load("c1", PRINCIPAL)).toBeNull();
  });

  it("serializes competing CAS calls so only one writer wins", async () => {
    const store = new JsonlConversationStore(dir);
    await store.compareAndSwap("c1", 0, makeSession());

    const results = await Promise.all([
      store.compareAndSwap("c1", 1, makeSession({ stateVersion: 2, lastAppliedTurnId: "turn-a" })),
      store.compareAndSwap("c1", 1, makeSession({ stateVersion: 2, lastAppliedTurnId: "turn-b" })),
    ]);

    expect(results.filter((result) => result.status === "saved")).toHaveLength(1);
    expect(results.filter((result) => result.status === "conflict")).toHaveLength(1);
  });

  it("keeps conversation lease ownership separate from the session", async () => {
    const now = 1_800_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(now);
    const store = new JsonlConversationStore(dir);

    expect(await store.claim("c1", "worker-a", 60_000)).toEqual({ status: "claimed" });
    expect(await store.claim("c1", "worker-b", 60_000)).toEqual({
      status: "rejected",
      holder: "worker-a",
      expiresAt: new Date(now + 60_000).toISOString(),
    });
    expect(readdirSync(path.join(dir, "sessions"))).not.toContain("c1.lease.json");
  });

  it("allows an expired lease takeover and reports the previous owner", async () => {
    const now = 1_800_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(now);
    const store = new JsonlConversationStore(dir);
    await store.claim("c1", "worker-a", 10);

    vi.mocked(Date.now).mockReturnValue(now + 11);
    expect(await store.claim("c1", "worker-b", 60_000)).toEqual({
      status: "force-claimed",
      previousHolder: "worker-a",
    });
  });

  it("only lets the lease owner release the conversation", async () => {
    const store = new JsonlConversationStore(dir);
    await store.claim("c1", "worker-a", 60_000);
    await store.release("c1", "worker-b");
    expect(await store.claim("c1", "worker-c", 60_000)).toMatchObject({ status: "rejected" });

    await store.release("c1", "worker-a");
    expect(await store.claim("c1", "worker-c", 60_000)).toEqual({ status: "claimed" });
  });

  it("looks up the persisted run for a duplicate turn id", async () => {
    const store = new JsonlConversationStore(dir);
    await store.compareAndSwap("c1", 0, makeSession());

    expect(await store.lookupTurn("c1", PRINCIPAL, "turn-1")).toEqual({ runId: "run-1" });
    expect(await store.lookupTurn("c1", PRINCIPAL, "turn-other")).toBeNull();
  });

  it("fails closed on principal mismatch without changing the source", async () => {
    const store = new JsonlConversationStore(dir);
    await store.compareAndSwap("c1", 0, makeSession());
    const file = path.join(dir, "sessions", "c1.json");
    const before = readFileSync(file, "utf8");

    await expect(store.load("c1", "attacker-001"))
      .rejects.toMatchObject({ code: "CONTEXT_PRINCIPAL_MISMATCH" });
    expect(readFileSync(file, "utf8")).toBe(before);
  });

  it("preserves malformed session bytes and returns a typed error", async () => {
    const store = new JsonlConversationStore(dir);
    const file = path.join(dir, "sessions", "c1.json");
    writeFileSync(file, "{malformed", "utf8");

    await expect(store.load("c1", PRINCIPAL))
      .rejects.toMatchObject({ code: "CONTEXT_DESERIALIZATION_FAILED" });
    expect(readFileSync(file, "utf8")).toBe("{malformed");
  });

  it("never lets the legacy save bridge overwrite a malformed source", async () => {
    const store = new JsonlConversationStore(dir);
    const file = path.join(dir, "sessions", "c1.json");
    writeFileSync(file, "{malformed", "utf8");

    await expect(store.save("c1", {
      lastContext: null,
      lastRunId: null,
      history: [],
      principalId: PRINCIPAL,
    })).rejects.toMatchObject({ code: "CONTEXT_DESERIALIZATION_FAILED" });
    expect(readFileSync(file, "utf8")).toBe("{malformed");
  });

  it("migrates legacy LastContext purely into a stale inherited frame", async () => {
    const store = new JsonlConversationStore(dir);
    const file = path.join(dir, "sessions", "legacy.json");
    const legacy: SessionState = {
      lastContext: {
        capabilityId: "MM.Inventory.GetAvailability",
        parameters: { material: "DEMOA2", plant: "5100" },
        missingParameters: [],
        decisionType: "SELECT",
      },
      lastRunId: "run-legacy",
      history: [{ role: "user", content: "legacy query" }],
      principalId: PRINCIPAL,
    };
    const source = JSON.stringify(legacy);
    writeFileSync(file, source, "utf8");

    const migrated = await store.load("legacy", PRINCIPAL);

    expect(migrated).toMatchObject({ schemaVersion: 2, stateVersion: 0 });
    expect(migrated?.activeFrame).toMatchObject({
      capabilityId: "MM.Inventory.GetAvailability",
      status: "STALE",
    });
    expect(migrated?.activeFrame?.slots.material).toMatchObject({
      value: "DEMOA2",
      state: "RESOLVED",
      provenance: "INHERITED_LEGACY",
    });
    expect(readFileSync(file, "utf8")).toBe(source);
  });

  it("uses atomic temp-write and rename without leaving temp files", async () => {
    const store = new JsonlConversationStore(dir);
    await store.compareAndSwap("c1", 0, makeSession());

    expect(readdirSync(path.join(dir, "sessions"))).toEqual(["c1.json"]);
    expect(JSON.parse(readFileSync(path.join(dir, "sessions", "c1.json"), "utf8")))
      .toEqual(makeSession());
  });
});
