import type { DurableRunStore } from "../durable/types";
import type { NodeLedgerEntry } from "./types";

export async function loadNodeLedger(
  store: DurableRunStore,
  runId: string
): Promise<Record<string, NodeLedgerEntry>> {
  const ref = await store.loadCheckpointRef(runId);
  if (!ref) return {};
  return (ref.nodeState as Record<string, NodeLedgerEntry>) ?? {};
}

export async function saveNodeLedger(
  store: DurableRunStore,
  runId: string,
  snapshotId: string,
  ledger: Record<string, NodeLedgerEntry>
): Promise<void> {
  // Bulk save: writes nodeState only (authority layer). Does NOT append
  // per-node events — transitionNode is the per-transition API that appends
  // a node_state_changed event. saveNodeLedger is used for initial load /
  // bulk hydration where individual transitions are not tracked.
  await store.appendCheckpointRef(runId, {
    registrySnapshotId: snapshotId,
    nodeState: ledger as Record<string, unknown>,
  });
}

export async function transitionNode(
  store: DurableRunStore,
  runId: string,
  snapshotId: string,
  nodeId: string,
  entry: NodeLedgerEntry
): Promise<void> {
  const ledger = await loadNodeLedger(store, runId);
  const fromState = ledger[nodeId]?.state ?? "INITIAL";
  ledger[nodeId] = entry;
  // nodeState 先写（权威恢复层）
  await saveNodeLedger(store, runId, snapshotId, ledger);
  // events 后 append（审计流 / SSE 重放层）
  const record = await store.load(runId);
  const sequence = (record?.events.length ?? 0) + 1;
  await store.appendEvent(runId, {
    runId,
    sequence,
    timestamp: entry.updatedAt,
    type: "node_state_changed",
    state: "running",
    nodeId,
    fromState,
    toState: entry.state,
    attempt: entry.attempt,
  });
}
