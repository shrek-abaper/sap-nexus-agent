import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "./jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord } from "./types";

const TTL = 60_000;
function seedRecord(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e], principalId: "local-user-0001" };
}

describe("lease", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "lease-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("first claim succeeds", async () => {
    const store = new JsonlRunStore(dir, "worker-A", TTL);
    await store.save("run-1", seedRecord("run-1"));
    expect(await store.claim("run-1", "worker-A", TTL)).toEqual({ status: "claimed" });
  });

  it("second worker claim while lease held is rejected (fail-closed)", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    const b = new JsonlRunStore(dir, "worker-B", TTL);
    await a.save("run-1", seedRecord("run-1"));
    await a.claim("run-1", "worker-A", TTL);
    const outcome = await b.claim("run-1", "worker-B", TTL);
    expect(outcome.status).toBe("rejected");
    if (outcome.status === "rejected") expect(outcome.holder).toBe("worker-A");
  });

  it("expired lease allows force-claimed takeover with audit", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    const b = new JsonlRunStore(dir, "worker-B", TTL);
    await a.save("run-1", seedRecord("run-1"));
    // claim with TTL=0 -> immediately expired
    await a.claim("run-1", "worker-A", 0);
    const outcome = await b.claim("run-1", "worker-B", TTL);
    expect(outcome.status).toBe("force-claimed");
    if (outcome.status === "force-claimed") expect(outcome.previousHolder).toBe("worker-A");
  });

  it("release allows another worker to claim", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    const b = new JsonlRunStore(dir, "worker-B", TTL);
    await a.save("run-1", seedRecord("run-1"));
    await a.claim("run-1", "worker-A", TTL);
    await a.release("run-1", "worker-A");
    expect((await b.claim("run-1", "worker-B", TTL)).status).toBe("claimed");
  });

  it("appendEvent renews the lease held by the same worker (activity-driven)", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    await a.save("run-1", seedRecord("run-1"));
    await a.claim("run-1", "worker-A", 10); // short TTL
    const before = await a.loadLeaseExpiry("run-1");
    await a.appendEvent("run-1", { runId: "run-1", sequence: 2, timestamp: "t2", type: "intent_parsed", state: "intent_parsed" });
    const after = await a.loadLeaseExpiry("run-1");
    expect(after).toBeGreaterThan(before ?? 0);
  });

  it("same worker re-claim is idempotent (claimed)", async () => {
    const a = new JsonlRunStore(dir, "worker-A", TTL);
    await a.save("run-1", seedRecord("run-1"));
    await a.claim("run-1", "worker-A", TTL);
    expect((await a.claim("run-1", "worker-A", TTL)).status).toBe("claimed");
  });
});
