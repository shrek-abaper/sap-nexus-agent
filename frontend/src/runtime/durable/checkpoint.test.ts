import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { appendFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "./jsonl-run-store";
import type { AgentRunRecord, CheckpointRef } from "./types";
import type { AgentRunEvent } from "../run-event-schema";

function seed(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e] };
}

describe("checkpoint ref", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "ckpt-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("appendCheckpointRef persists and loadCheckpointRef returns latest", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    const ref1: CheckpointRef = { registrySnapshotId: "snap-1", nodeState: { nodeA: "pending" } };
    await store.appendCheckpointRef("run-1", ref1);
    expect(await store.loadCheckpointRef("run-1")).toEqual(ref1);
  });

  it("keeps the latest checkpoint_ref when appended multiple times (state-change replay)", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    await store.appendCheckpointRef("run-1", { registrySnapshotId: "snap-1", nodeState: { a: "pending" } });
    await store.appendCheckpointRef("run-1", { registrySnapshotId: "snap-1", nodeState: { a: "approved" }, approvalRecordRef: "apr-1" });
    const loaded = await store.loadCheckpointRef("run-1");
    expect(loaded?.nodeState).toEqual({ a: "approved" });
    expect(loaded?.approvalRecordRef).toBe("apr-1");
  });

  it("returns null when no checkpoint_ref exists (fail-closed: caller treats as missing)", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    expect(await store.loadCheckpointRef("run-1")).toBeNull();
  });

  it("recovers checkpoint_ref across store instances (cross-restart)", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    await store.appendCheckpointRef("run-1", { registrySnapshotId: "snap-1", nodeState: { x: 1 } });
    const reopened = new JsonlRunStore(dir);
    expect(await reopened.loadCheckpointRef("run-1")).toEqual({ registrySnapshotId: "snap-1", nodeState: { x: 1 } });
  });

  it("loadCheckpointRef is independent of AgentRunRecord load (PlanExecutionState authority layer)", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    await store.appendCheckpointRef("run-1", { registrySnapshotId: "snap-1", nodeState: {} });
    const record = await store.load("run-1");
    // AgentRunRecord does NOT carry checkpointRef (authority layer is separate from event stream)
    expect((record as unknown as { checkpointRef?: unknown }).checkpointRef).toBeUndefined();
    expect(await store.loadCheckpointRef("run-1")).not.toBeNull();
  });

  it("skips corrupt lines and returns latest valid checkpoint_ref (fail-closed)", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    const file = path.join(dir, "runs", "run-1.jsonl");
    // corrupt line before the valid checkpoint_ref
    appendFileSync(file, "{INVALID JSON\n");
    const ref: CheckpointRef = { registrySnapshotId: "snap-1", nodeState: { a: "ok" } };
    await store.appendCheckpointRef("run-1", ref);
    // corrupt line after the valid checkpoint_ref
    appendFileSync(file, "{ALSO BROKEN\n");
    const loaded = await store.loadCheckpointRef("run-1");
    expect(loaded).toEqual(ref);
  });
});
