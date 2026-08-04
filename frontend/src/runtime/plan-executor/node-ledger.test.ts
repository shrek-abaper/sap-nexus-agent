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

  it("transitionNode appends a node_state_changed event to the event stream", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await transitionNode(store, "run-1", SNAP, "nodeA", entry(NodeState.VALIDATING, 1));
    const record = await store.load("run-1");
    expect(record).not.toBeNull();
    const nodeEvent = record!.events.find((e) => e.type === "node_state_changed");
    expect(nodeEvent).toBeDefined();
    expect(nodeEvent!.nodeId).toBe("nodeA");
    expect(nodeEvent!.fromState).toBe("INITIAL");
    expect(nodeEvent!.toState).toBe(NodeState.VALIDATING);
    expect(nodeEvent!.attempt).toBe(1);
    // seed event was sequence 1; node_state_changed must be the next sequence
    expect(nodeEvent!.sequence).toBe(2);
  });

  it("transitionNode event sequence is monotonic across multiple transitions", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await transitionNode(store, "run-1", SNAP, "nodeA", entry(NodeState.READY));
    await transitionNode(store, "run-1", SNAP, "nodeA", entry(NodeState.VALIDATING, 1));
    await transitionNode(store, "run-1", SNAP, "nodeB", entry(NodeState.EXECUTING));
    const record = await store.load("run-1");
    const nodeEvents = record!.events.filter((e) => e.type === "node_state_changed");
    expect(nodeEvents).toHaveLength(3);
    // sequences must be strictly increasing
    expect(nodeEvents[0]!.sequence).toBe(2);
    expect(nodeEvents[1]!.sequence).toBe(3);
    expect(nodeEvents[2]!.sequence).toBe(4);
  });

  it("transitionNode records prior state as fromState on subsequent transitions", async () => {
    const store = new JsonlRunStore(dir, "worker-A");
    await store.save("run-1", seed("run-1"));
    await transitionNode(store, "run-1", SNAP, "nodeA", entry(NodeState.READY));
    await transitionNode(store, "run-1", SNAP, "nodeA", entry(NodeState.VALIDATING, 1));
    const record = await store.load("run-1");
    const nodeEvents = record!.events.filter((e) => e.type === "node_state_changed");
    expect(nodeEvents).toHaveLength(2);
    expect(nodeEvents[0]!.fromState).toBe("INITIAL");
    expect(nodeEvents[0]!.toState).toBe(NodeState.READY);
    expect(nodeEvents[1]!.fromState).toBe(NodeState.READY);
    expect(nodeEvents[1]!.toState).toBe(NodeState.VALIDATING);
  });
});
