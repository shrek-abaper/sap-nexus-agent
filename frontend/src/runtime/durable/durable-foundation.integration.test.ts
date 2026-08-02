import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlConversationStore } from "./jsonl-conversation-store";
import { JsonlRunStore } from "./jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord, WorkbenchOutcome } from "./types";

function runRecord(runId: string, state: AgentRunEvent["state"]): AgentRunRecord {
  return { runId, query: "q", events: [{ runId, sequence: 1, timestamp: "t", type: "run_started", state }], principalId: "local-user-0001" };
}

describe("durable foundation integration", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "integ-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("cross-restart: pending/awaiting_approval/awaiting_batch_confirm runs recover", async () => {
    const store = new JsonlRunStore(dir, "w1");
    const outcome: WorkbenchOutcome = { status: "awaiting_approval" };
    await store.save("run-pending", runRecord("run-pending", "running"));
    await store.appendPendingOutcome("run-pending", outcome);
    await store.save("run-appr", runRecord("run-appr", "awaiting_approval"));
    await store.appendPendingOutcome("run-appr", outcome);
    await store.save("run-batch", runRecord("run-batch", "awaiting_batch_confirm"));
    await store.appendPendingOutcome("run-batch", { status: "awaiting_batch_confirm" });

    const restarted = new JsonlRunStore(dir, "w1");
    for (const runId of ["run-pending", "run-appr", "run-batch"]) {
      const rec = await restarted.load(runId);
      expect(rec?.pendingOutcome).toBeDefined();
    }
    const awaiting = await restarted.list({ state: "awaiting_approval" });
    expect(awaiting.map((r) => r.runId)).toContain("run-appr");
  });

  it("multi-worker: worker B reads worker A's run; lease fail-closed on concurrent claim", async () => {
    const a = new JsonlRunStore(dir, "wA");
    const b = new JsonlRunStore(dir, "wB");
    await a.save("run-shared", runRecord("run-shared", "awaiting_approval"));
    await a.appendPendingOutcome("run-shared", { status: "awaiting_approval" });
    // worker B reads shared state
    expect((await b.load("run-shared"))?.pendingOutcome?.status).toBe("awaiting_approval");
    // worker A claims; worker B rejected
    await a.claim("run-shared", "wA", 60_000);
    const takeover = await b.claim("run-shared", "wB", 60_000);
    expect(takeover.status).toBe("rejected");
  });

  it("checkpoint replay: latest nodeState recovered across restart", async () => {
    const store = new JsonlRunStore(dir, "w1");
    await store.save("run-ckpt", runRecord("run-ckpt", "running"));
    await store.appendCheckpointRef("run-ckpt", { registrySnapshotId: "snap-1", nodeState: { n1: "pending" } });
    await store.appendEvent("run-ckpt", { runId: "run-ckpt", sequence: 2, timestamp: "t2", type: "approval_state_changed", state: "awaiting_approval" });
    await store.appendCheckpointRef("run-ckpt", { registrySnapshotId: "snap-1", nodeState: { n1: "approved" }, approvalRecordRef: "apr-1" });

    const restarted = new JsonlRunStore(dir, "w1");
    const ref = await restarted.loadCheckpointRef("run-ckpt");
    expect(ref?.nodeState).toEqual({ n1: "approved" });
    expect(ref?.approvalRecordRef).toBe("apr-1");
  });

  it("idempotent continuation: duplicate key does not re-execute", async () => {
    const store = new JsonlRunStore(dir, "w1");
    const key = "run-1:approval_approve:abc";
    const result: WorkbenchOutcome = { status: "success", responseText: "done" };
    await store.markExecuted(key, result);
    expect(await store.lookupExecuted(key)).toEqual(result);
    // second lookup returns same result (no re-execution path)
    expect(await store.lookupExecuted(key)).toEqual(result);
  });

  it("conversational-context regression: session resumes lastContext + history across restart", async () => {
    const conv = new JsonlConversationStore(dir);
    await conv.save("c1", {
      lastContext: { capabilityId: "cap-1", parameters: { m: "1" }, missingParameters: [], decisionType: "CLARIFY" },
      lastRunId: "run-1",
      history: [{ role: "user", content: "hi" }, { role: "assistant", content: "你好" }]
    });
    const restarted = new JsonlConversationStore(dir);
    const loaded = await restarted.load("c1");
    expect(loaded?.lastContext?.capabilityId).toBe("cap-1");
    expect(loaded?.history.length).toBe(2);
    expect(loaded?.lastRunId).toBe("run-1");
  });
});
