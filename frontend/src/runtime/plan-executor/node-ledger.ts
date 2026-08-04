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
  // nodeState 先写（权威恢复层）
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
  ledger[nodeId] = entry;
  await saveNodeLedger(store, runId, snapshotId, ledger);
}
