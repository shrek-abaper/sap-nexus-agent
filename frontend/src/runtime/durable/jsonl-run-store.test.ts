import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { appendFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "./jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord, WorkbenchOutcome } from "./types";

function event(runId: string, sequence: number, type: AgentRunEvent["type"], state: AgentRunEvent["state"]): AgentRunEvent {
  return { runId, sequence, timestamp: "2026-08-02T00:00:00Z", type, state };
}

function record(runId: string, query: string, events: AgentRunEvent[]): AgentRunRecord {
  return { runId, query, events, principalId: "local-user-0001" };
}

describe("JsonlRunStore core", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "run-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("returns null when run does not exist", async () => {
    const store = new JsonlRunStore(dir);
    expect(await store.load("run-x")).toBeNull();
  });

  it("saves and loads a run with full event stream", async () => {
    const store = new JsonlRunStore(dir);
    const events = [event("run-1", 1, "run_started", "running"), event("run-1", 2, "run_completed", "completed")];
    await store.save("run-1", record("run-1", "query text", events));
    const loaded = await store.load("run-1");
    expect(loaded).toEqual({ ...record("run-1", "query text", events), principalId: "local-user-0001" });
  });

  it("appendEvent adds events incrementally and persists via fsync", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", record("run-1", "q", [event("run-1", 1, "run_started", "running")]));
    await store.appendEvent("run-1", event("run-1", 2, "intent_parsed", "intent_parsed"));
    const loaded = await store.load("run-1");
    expect(loaded?.events.map((e) => e.sequence)).toEqual([1, 2]);
  });

  it("rejects duplicate or skipped event sequences before append", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", record("run-1", "q", [event("run-1", 1, "run_started", "running")]));

    await expect(store.appendEvent("run-1", event("run-1", 1, "intent_parsed", "intent_parsed")))
      .rejects.toThrow("expected sequence 2");
    await expect(store.appendEvent("run-1", event("run-1", 3, "intent_parsed", "intent_parsed")))
      .rejects.toThrow("expected sequence 2");
    expect((await store.load("run-1"))?.events.map((entry) => entry.sequence)).toEqual([1]);
  });

  it("rejects a non-contiguous event stream on initial save", async () => {
    const store = new JsonlRunStore(dir);
    const events = [event("run-1", 1, "run_started", "running"), event("run-1", 3, "run_completed", "completed")];

    await expect(store.save("run-1", record("run-1", "q", events))).rejects.toThrow("expected sequence 2");
    expect(await store.load("run-1")).toBeNull();
  });

  it("recovers full record across store instances (cross-restart replay)", async () => {
    const store = new JsonlRunStore(dir);
    const events = [event("run-1", 1, "run_started", "running"), event("run-1", 2, "run_completed", "completed")];
    await store.save("run-1", record("run-1", "q", [events[0]]));
    await store.appendEvent("run-1", events[1]);
    const outcome: WorkbenchOutcome = { status: "awaiting_approval" };
    await store.appendPendingOutcome("run-1", outcome);
    await store.appendDecision("run-1", "approve");

    const reopened = new JsonlRunStore(dir);
    const loaded = await reopened.load("run-1");
    expect(loaded?.query).toBe("q");
    expect(loaded?.events).toEqual(events);
    expect(loaded?.pendingOutcome).toEqual(outcome);
    expect(loaded?.decision).toBe("approve");
  });

  it("appendPendingOutcome keeps the latest value", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", record("run-1", "q", [event("run-1", 1, "run_started", "running")]));
    await store.appendPendingOutcome("run-1", { status: "awaiting_approval" });
    await store.appendPendingOutcome("run-1", { status: "awaiting_batch_confirm" });
    expect((await store.load("run-1"))?.pendingOutcome?.status).toBe("awaiting_batch_confirm");
  });

  it("list returns all runs, optionally filtered by last state", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", record("run-1", "q", [event("run-1", 1, "run_started", "running"), event("run-1", 2, "approval_state_changed", "awaiting_approval")]));
    await store.save("run-2", record("run-2", "q", [event("run-2", 1, "run_started", "running"), event("run-2", 2, "run_completed", "completed")]));
    expect((await store.list()).length).toBe(2);
    expect((await store.list({ state: "awaiting_approval" })).map((r) => r.runId)).toEqual(["run-1"]);
  });

  it("clearAll removes all runs", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", record("run-1", "q", [event("run-1", 1, "run_started", "running")]));
    await store.clearAll();
    expect(await store.load("run-1")).toBeNull();
  });

  it("replay skips corrupt lines and recovers valid record (fail-closed, consistent with loadCheckpointRef)", async () => {
    const store = new JsonlRunStore(dir);
    const events = [event("run-1", 1, "run_started", "running"), event("run-1", 2, "run_completed", "completed")];
    await store.save("run-1", record("run-1", "query text", events));
    // simulate a partially-written (corrupt) line appended by a crash mid-write
    appendFileSync(path.join(dir, "runs", "run-1.jsonl"), "not valid json\n", "utf8");
    const loaded = await store.load("run-1");
    expect(loaded?.runId).toBe("run-1");
    expect(loaded?.query).toBe("query text");
    expect(loaded?.events).toEqual(events);
  });

  it("save persists principalId in run_meta and load returns it", async () => {
    const store = new JsonlRunStore(dir);
    const events = [event("run-1", 1, "run_started", "running")];
    await store.save("run-1", { runId: "run-1", query: "q", events, principalId: "user-a" });
    const loaded = await store.load("run-1");
    expect(loaded?.principalId).toBe("user-a");
  });

  it("load backfills principalId to local-user-0001 for legacy records", async () => {
    const store = new JsonlRunStore(dir);
    // write a legacy run_meta line without principalId by appending raw JSONL
    const legacyLine = JSON.stringify({ kind: "run_meta", runId: "run-legacy", query: "old" }) + "\n" +
      JSON.stringify({ kind: "event", runId: "run-legacy", sequence: 1, timestamp: "2026-08-02T00:00:00Z", type: "run_started", state: "running" }) + "\n";
    appendFileSync(path.join(dir, "runs", "run-legacy.jsonl"), legacyLine);
    const loaded = await store.load("run-legacy");
    expect(loaded?.principalId).toBe("local-user-0001");
  });

  it("list filters by principalId", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-a", { runId: "run-a", query: "q", events: [event("run-a", 1, "run_started", "running")], principalId: "user-a" });
    await store.save("run-b", { runId: "run-b", query: "q", events: [event("run-b", 1, "run_started", "running")], principalId: "user-b" });
    expect((await store.list({ principalId: "user-a" })).map((r) => r.runId)).toEqual(["run-a"]);
    expect((await store.list({ principalId: "user-b" })).map((r) => r.runId)).toEqual(["run-b"]);
    expect((await store.list()).length).toBe(2);
  });
});
