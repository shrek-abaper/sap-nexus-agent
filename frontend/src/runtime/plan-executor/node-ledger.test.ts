import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import type { AgentRunEvent } from "../run-event-schema";
import type { AgentRunRecord } from "../durable/types";
import { NodeState } from "./types";
import { loadNodeLedger, saveNodeLedger, transitionNode } from "./node-ledger";

const SNAP = "sha256:snap-001";

function seed(runId: string): AgentRunRecord {
  const e: AgentRunEvent = { runId, sequence: 1, timestamp: "t", type: "run_started", state: "running" };
  return { runId, query: "q", events: [e], principalId: "local-user-0001" };
}

function entry(state: NodeState, attempt = 0): import("./types").NodeLedgerEntry {
  return { state, attempt, inputHash: "hash-001", resultRef: null, traceSpan: null, updatedAt: "2026-08-04T00:00:00Z" };
}

describe("node ledger", () => {
  let dir: string;
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), "ledger-")); });
  afterEach(() => { rmSync(dir, { recursive: true, force: true }); });

  it("saveNodeLedger persists and loadNodeLedger returns the ledger", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, { nodeA: entry(NodeState.READY) });
    const loaded = await loadNodeLedger(store, "run-1");
    expect(loaded).toEqual({ nodeA: entry(NodeState.READY) });
  });

  it("loadNodeLedger returns empty object when no checkpoint_ref exists", async () => {
    const store = new JsonlRunStore(dir);
    await store.save("run-1", seed("run-1"));
    expect(await loadNodeLedger(store, "run-1")).toEqual({});
  });

  it("recovers across store instances (cross-restart)", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, {
      nodeA: entry(NodeState.SUCCEEDED),
      nodeB: entry(NodeState.READY),
    });
    const reopened = new JsonlRunStore(dir, "worker-B");
    const loaded = await loadNodeLedger(reopened, "run-1");
    expect(loaded.nodeA.state).toBe(NodeState.SUCCEEDED);
    expect(loaded.nodeB.state).toBe(NodeState.READY);
  });

  it("transitionNode updates a single node entry and preserves others", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, { nodeA: entry(NodeState.READY) });
    await transitionNode(store, "run-1", SNAP, "nodeA", entry(NodeState.VALIDATING));
    const loaded = await loadNodeLedger(store, "run-1");
    expect(loaded.nodeA.state).toBe(NodeState.VALIDATING);
  });

  it("transitionNode preserves other nodes when updating one", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await saveNodeLedger(store, "run-1", SNAP, {
      nodeA: entry(NodeState.SUCCEEDED),
      nodeB: entry(NodeState.READY),
    });
    await transitionNode(store, "run-1", SNAP, "nodeB", entry(NodeState.VALIDATING));
    const loaded = await loadNodeLedger(store, "run-1");
    expect(loaded.nodeA.state).toBe(NodeState.SUCCEEDED);
    expect(loaded.nodeB.state).toBe(NodeState.VALIDATING);
  });
});
