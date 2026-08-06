import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
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
    vi.useRealTimers();
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

  it.each([
    ["slot clarification", {
      kind: "SLOT_CLARIFICATION" as const,
      frameId: "frame-1",
      expectedFields: ["material"],
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["capability choice", {
      kind: "CAPABILITY_CHOICE" as const,
      frameId: "pending:choice:1",
      capabilityIds: ["MM.PurchaseOrder.GetList"],
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["batch confirmation", {
      kind: "BATCH_CONFIRMATION" as const,
      frameId: "frame-1",
      batchRef: "sha256:batch-1",
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["planner confirmation", {
      kind: "PLANNER_CONFIRMATION" as const,
      frameId: "pending:planner:1",
      plannerRef: "sha256:planner-1",
      plannerGoals: [{
        capabilityId: "MM.PurchaseOrder.GetList",
        parameters: { vendor: "1000" },
        missing: [],
      }],
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
  ])("round-trips strict typed pending: %s", async (_label, pendingInteraction) => {
    const store = new JsonlConversationStore(dir);
    const session = makeSession({ pendingInteraction });

    await expect(store.compareAndSwap("c1", 0, session)).resolves.toEqual({
      status: "saved",
      stateVersion: 1,
    });
    await expect(new JsonlConversationStore(dir).load("c1", PRINCIPAL))
      .resolves.toEqual(session);
  });

  it.each([
    ["cross-kind slot field", {
      kind: "CAPABILITY_CHOICE",
      frameId: "pending:choice:1",
      expectedFields: ["capabilityId"],
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["approval authority", {
      kind: "BATCH_CONFIRMATION",
      frameId: "frame-1",
      batchRef: "sha256:batch-1",
      approvalId: "forged",
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["technical authority", {
      kind: "PLANNER_CONFIRMATION",
      frameId: "pending:planner:1",
      plannerRef: "sha256:planner-1",
      plannerGoals: [],
      bindingId: "forged",
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["malformed planner goal", {
      kind: "PLANNER_CONFIRMATION",
      frameId: "pending:planner:1",
      plannerRef: "sha256:planner-1",
      plannerGoals: [{ capabilityId: "MM.PurchaseOrder.GetList", parameters: [], missing: [] }],
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["empty slot field", {
      kind: "SLOT_CLARIFICATION",
      frameId: "frame-1",
      expectedFields: [""],
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["empty capability id", {
      kind: "CAPABILITY_CHOICE",
      frameId: "pending:choice:1",
      capabilityIds: [""],
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["empty planner missing field", {
      kind: "PLANNER_CONFIRMATION",
      frameId: "pending:planner:1",
      plannerRef: "sha256:planner-1",
      plannerGoals: [{
        capabilityId: "MM.PurchaseOrder.GetList",
        parameters: { vendor: "1000" },
        missing: [""],
      }],
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
    ["empty planner parameter value", {
      kind: "PLANNER_CONFIRMATION",
      frameId: "pending:planner:1",
      plannerRef: "sha256:planner-1",
      plannerGoals: [{
        capabilityId: "MM.PurchaseOrder.GetList",
        parameters: { vendor: "" },
        missing: [],
      }],
      stateVersion: 1,
      registrySnapshotId: "snapshot-1",
      expiresAt: "2099-01-01T00:00:00Z",
    }],
  ])("rejects malformed pending %s without changing source bytes", async (_label, pending) => {
    new JsonlConversationStore(dir);
    const file = path.join(dir, "sessions", "invalid-pending.json");
    const source = JSON.stringify({ ...makeSession(), pendingInteraction: pending });
    writeFileSync(file, source, "utf8");

    await expect(new JsonlConversationStore(dir).load("invalid-pending", PRINCIPAL))
      .rejects.toMatchObject({ code: "CONTEXT_DESERIALIZATION_FAILED" });
    expect(readFileSync(file, "utf8")).toBe(source);
  });

  it.each([
    "",
    "tomorrow",
    "2026-08-06T09:15:00",
    "2026-02-30T09:15:00Z",
  ])("rejects non-UTC or invalid ISO pending expiry %s", async (expiresAt) => {
    new JsonlConversationStore(dir);
    const file = path.join(dir, "sessions", "invalid-expiry.json");
    const source = JSON.stringify({
      ...makeSession(),
      pendingInteraction: {
        kind: "CAPABILITY_CHOICE",
        frameId: "pending:choice:1",
        capabilityIds: ["MM.PurchaseOrder.GetList"],
        stateVersion: 1,
        registrySnapshotId: "snapshot-1",
        expiresAt,
      },
    });
    writeFileSync(file, source, "utf8");

    await expect(new JsonlConversationStore(dir).load("invalid-expiry", PRINCIPAL))
      .rejects.toMatchObject({ code: "CONTEXT_DESERIALIZATION_FAILED" });
    expect(readFileSync(file, "utf8")).toBe(source);
  });

  it("rejects duplicate planner capability ids", async () => {
    new JsonlConversationStore(dir);
    const file = path.join(dir, "sessions", "duplicate-planner.json");
    const goal = {
      capabilityId: "MM.Inventory.GetAvailability",
      parameters: { material: "DEMOA2" },
      missing: ["plant"],
    };
    writeFileSync(file, JSON.stringify({
      ...makeSession(),
      pendingInteraction: {
        kind: "PLANNER_CONFIRMATION",
        frameId: "pending:planner:1",
        plannerRef: "sha256:planner-1",
        plannerGoals: [goal, goal],
        stateVersion: 1,
        registrySnapshotId: "snapshot-1",
        expiresAt: "2026-08-06T09:15:00Z",
      },
    }), "utf8");

    await expect(new JsonlConversationStore(dir).load("duplicate-planner", PRINCIPAL))
      .rejects.toMatchObject({ code: "CONTEXT_DESERIALIZATION_FAILED" });
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

    expect(await store.claim("c1", "worker-a", 60_000)).toEqual({
      status: "claimed",
      fenceToken: expect.any(String),
      expiresAt: new Date(now + 60_000).toISOString(),
    });
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
      fenceToken: expect.any(String),
      expiresAt: new Date(now + 60_011).toISOString(),
    });
  });

  it("only lets the lease owner release the conversation", async () => {
    const store = new JsonlConversationStore(dir);
    const claimed = await store.claim("c1", "worker-a", 60_000) as unknown as { fenceToken: string };
    await store.release("c1", "worker-b", claimed.fenceToken);
    expect(await store.claim("c1", "worker-c", 60_000)).toMatchObject({ status: "rejected" });

    await store.release("c1", "worker-a", claimed.fenceToken);
    expect(await store.claim("c1", "worker-c", 60_000)).toMatchObject({
      status: "claimed",
      fenceToken: expect.any(String),
    });
  });

  it("renews only the current unexpired fenced lease", async () => {
    const now = 1_800_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(now);
    const store = new JsonlConversationStore(dir);
    const first = await store.claim("c1", "worker-a", 100) as unknown as { fenceToken: string };
    const renew = store as unknown as {
      renew: (conversationId: string, workerId: string, fenceToken: string, ttlMs: number) =>
        Promise<{ status: string; expiresAt?: string }>;
    };

    vi.mocked(Date.now).mockReturnValue(now + 50);
    await expect(renew.renew("c1", "worker-a", first.fenceToken, 100)).resolves.toEqual({
      status: "owned",
      expiresAt: new Date(now + 150).toISOString(),
    });
    vi.mocked(Date.now).mockReturnValue(now + 151);
    await expect(renew.renew("c1", "worker-a", first.fenceToken, 100)).resolves.toMatchObject({
      status: "lost",
    });
  });

  it("does not let a stale fence release a newer lease with the same owner id", async () => {
    const now = 1_800_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(now);
    const store = new JsonlConversationStore(dir);
    const first = await store.claim("c1", "worker-a", 10) as unknown as { fenceToken: string };
    vi.mocked(Date.now).mockReturnValue(now + 11);
    const second = await store.claim("c1", "worker-a", 60_000) as unknown as { fenceToken: string };

    expect(second.fenceToken).not.toBe(first.fenceToken);
    await store.release("c1", "worker-a", first.fenceToken);
    expect(await store.claim("c1", "worker-b", 60_000)).toMatchObject({
      status: "rejected",
      holder: "worker-a",
    });
  });

  it("rejects a stale fenced CAS atomically after lease takeover", async () => {
    const now = 1_800_000_000_000;
    vi.spyOn(Date, "now").mockReturnValue(now);
    const store = new JsonlConversationStore(dir);
    const first = await store.claim("c1", "worker-a", 10) as unknown as { fenceToken: string };
    vi.mocked(Date.now).mockReturnValue(now + 11);
    await store.claim("c1", "worker-b", 60_000);

    await expect(store.compareAndSwap("c1", 0, makeSession(), {
      workerId: "worker-a",
      fenceToken: first.fenceToken,
    })).resolves.toMatchObject({ status: "lease-lost", holder: "worker-b" });
    expect(await store.load("c1", PRINCIPAL)).toBeNull();
  });

  it("looks up the persisted run for a duplicate turn id", async () => {
    const store = new JsonlConversationStore(dir);
    await store.compareAndSwap("c1", 0, makeSession());

    expect(await store.lookupTurn("c1", PRINCIPAL, "turn-1")).toEqual({ runId: "run-1" });
    expect(await store.lookupTurn("c1", PRINCIPAL, "turn-other")).toBeNull();
  });

  it("retains older turn mappings across later CAS updates and store restarts", async () => {
    const store = new JsonlConversationStore(dir);
    await store.compareAndSwap("c1", 0, makeSession());
    await store.compareAndSwap("c1", 1, makeSession({
      stateVersion: 2,
      lastAppliedTurnId: "turn-2",
      lastRunId: "run-2",
    }));

    const reopened = new JsonlConversationStore(dir);
    expect(await reopened.lookupTurn("c1", PRINCIPAL, "turn-1")).toEqual({ runId: "run-1" });
    expect(await reopened.lookupTurn("c1", PRINCIPAL, "turn-2")).toEqual({ runId: "run-2" });
  });

  it("bounds the durable turn ledger to the newest 64 turns", async () => {
    const store = new JsonlConversationStore(dir);
    for (let index = 1; index <= 65; index += 1) {
      await store.compareAndSwap("c1", index - 1, makeSession({
        stateVersion: index,
        lastAppliedTurnId: `turn-${index}`,
        lastRunId: `run-${index}`,
      }));
    }

    const reopened = new JsonlConversationStore(dir);
    expect(await reopened.lookupTurn("c1", PRINCIPAL, "turn-1")).toBeNull();
    expect(await reopened.lookupTurn("c1", PRINCIPAL, "turn-2")).toEqual({ runId: "run-2" });
    expect(await reopened.lookupTurn("c1", PRINCIPAL, "turn-65")).toEqual({ runId: "run-65" });
  });

  it("reconciles a committed Session before a later CAS can overwrite its ledger fallback", async () => {
    let failLedgerRename = true;
    const store = new JsonlConversationStore(dir, (boundary) => {
      if (failLedgerRename && boundary.artifact === "turn-ledger" && boundary.phase === "before-rename") {
        failLedgerRename = false;
        throw new Error("injected ledger rename failure");
      }
    });

    await expect(store.compareAndSwap("c1", 0, makeSession()))
      .rejects.toThrow("injected ledger rename failure");
    expect(JSON.parse(readFileSync(path.join(dir, "sessions", "c1.json"), "utf8")))
      .toMatchObject({ stateVersion: 1, lastAppliedTurnId: "turn-1", lastRunId: "run-1" });

    const reopened = new JsonlConversationStore(dir);
    await expect(reopened.compareAndSwap("c1", 1, makeSession({
      stateVersion: 2,
      lastAppliedTurnId: "turn-2",
      lastRunId: "run-2",
    }))).resolves.toEqual({ status: "saved", stateVersion: 2 });
    expect(await reopened.lookupTurn("c1", PRINCIPAL, "turn-1")).toEqual({ runId: "run-1" });
    expect(await reopened.lookupTurn("c1", PRINCIPAL, "turn-2")).toEqual({ runId: "run-2" });
  });

  it("does not precommit a prepared transaction when Session rename fails", async () => {
    let failSessionRename = true;
    const store = new JsonlConversationStore(dir, (boundary) => {
      if (failSessionRename && boundary.artifact === "session" && boundary.phase === "before-rename") {
        failSessionRename = false;
        throw new Error("injected Session rename failure");
      }
    });

    await expect(store.compareAndSwap("c1", 0, makeSession()))
      .rejects.toThrow("injected Session rename failure");

    const reopened = new JsonlConversationStore(dir);
    expect(await reopened.load("c1", PRINCIPAL)).toBeNull();
    expect(await reopened.lookupTurn("c1", PRINCIPAL, "turn-1")).toBeNull();
  });

  it("does not change Session bytes when prepared-journal write fails", async () => {
    const original = makeSession();
    const store = new JsonlConversationStore(dir);
    await store.compareAndSwap("c1", 0, original);
    const sessionFile = path.join(dir, "sessions", "c1.json");
    const source = readFileSync(sessionFile, "utf8");
    const failing = new JsonlConversationStore(dir, (boundary) => {
      if (boundary.artifact === "transaction" && boundary.phase === "before-write") {
        throw new Error("injected transaction write failure");
      }
    });

    await expect(failing.compareAndSwap("c1", 1, makeSession({
      stateVersion: 2,
      lastAppliedTurnId: "turn-2",
      lastRunId: "run-2",
    }))).rejects.toThrow("injected transaction write failure");
    expect(readFileSync(sessionFile, "utf8")).toBe(source);
    expect(await new JsonlConversationStore(dir).lookupTurn("c1", PRINCIPAL, "turn-2")).toBeNull();
  });

  it("preserves malformed recovery journal and Session bytes while failing closed", async () => {
    const store = new JsonlConversationStore(dir);
    await store.compareAndSwap("c1", 0, makeSession());
    const sessionFile = path.join(dir, "sessions", "c1.json");
    const sessionSource = readFileSync(sessionFile, "utf8");
    const transactionsDir = path.join(dir, "conversation-transactions");
    mkdirSync(transactionsDir, { recursive: true });
    const transactionFile = path.join(transactionsDir, "c1.json");
    const transactionSource = "{malformed-journal";
    writeFileSync(transactionFile, transactionSource, "utf8");

    const reopened = new JsonlConversationStore(dir);
    await expect(reopened.load("c1", PRINCIPAL))
      .rejects.toMatchObject({ code: "CONTEXT_DESERIALIZATION_FAILED" });
    await expect(reopened.compareAndSwap("c1", 1, makeSession({ stateVersion: 2 })))
      .rejects.toMatchObject({ code: "CONTEXT_DESERIALIZATION_FAILED" });
    expect(readFileSync(sessionFile, "utf8")).toBe(sessionSource);
    expect(readFileSync(transactionFile, "utf8")).toBe(transactionSource);
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

  it("accepts an explicitly versioned schema-v1 legacy session", async () => {
    const store = new JsonlConversationStore(dir);
    const file = path.join(dir, "sessions", "legacy-v1.json");
    const source = JSON.stringify({
      schemaVersion: 1,
      lastContext: null,
      lastRunId: "run-legacy-v1",
      history: [{ role: "user", content: "legacy query" }],
      principalId: PRINCIPAL,
    });
    writeFileSync(file, source, "utf8");

    await expect(store.load("legacy-v1", PRINCIPAL)).resolves.toMatchObject({
      schemaVersion: 2,
      stateVersion: 0,
      lastRunId: "run-legacy-v1",
    });
    expect(readFileSync(file, "utf8")).toBe(source);
  });

  it.each([
    ["empty object", "{}"],
    ["unsupported schema", JSON.stringify({ ...makeSession(), schemaVersion: 3 })],
    ["malformed legacy field", JSON.stringify({
      lastContext: null,
      lastRunId: 42,
      history: [],
      principalId: PRINCIPAL,
    })],
    ["ambiguous legacy and v2 fields", JSON.stringify({
      lastContext: null,
      lastRunId: null,
      history: [],
      principalId: PRINCIPAL,
      activeFrame: null,
    })],
  ])("rejects %s without changing exact source bytes", async (_label, source) => {
    const store = new JsonlConversationStore(dir);
    const file = path.join(dir, "sessions", "invalid-legacy.json");
    writeFileSync(file, source, "utf8");

    await expect(store.load("invalid-legacy", PRINCIPAL))
      .rejects.toMatchObject({ code: "CONTEXT_DESERIALIZATION_FAILED" });
    expect(readFileSync(file, "utf8")).toBe(source);
    await expect(store.save("invalid-legacy", {
      lastContext: null,
      lastRunId: null,
      history: [],
      principalId: PRINCIPAL,
    })).rejects.toMatchObject({ code: "CONTEXT_DESERIALIZATION_FAILED" });
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
