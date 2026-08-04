// frontend/src/runtime/plan-executor/dag-scheduler.ts
import type { PlanGraphV2, NodeLedgerEntry, NodeState } from "./types";

const TERMINAL_OR_ACTIVE: ReadonlySet<NodeState> = new Set([
  "SUCCEEDED" as NodeState,
  "FAILED" as NodeState,
  "TIMED_OUT" as NodeState,
  "CANCELLED" as NodeState,
  "VALIDATING" as NodeState,
  "EXECUTING" as NodeState,
  "BLOCKED_APPROVAL" as NodeState,
]);

export function getDependencies(graph: PlanGraphV2, nodeId: string): string[] {
  return graph.edges
    .filter(
      (e) =>
        (e.kind === "dependency" || e.kind === "data") && e.toNodeId === nodeId
    )
    .map((e) => e.fromNodeId);
}

export function selectReadyNodes(
  graph: PlanGraphV2,
  ledger: Record<string, NodeLedgerEntry>,
  maxConcurrency?: number
): string[] {
  const cap = maxConcurrency ?? getMaxConcurrency();
  const ready: string[] = [];
  for (const nodeId of graph.readPartition) {
    const entry = ledger[nodeId];
    // Skip nodes already in a terminal or active state
    if (entry && TERMINAL_OR_ACTIVE.has(entry.state)) continue;
    const deps = getDependencies(graph, nodeId);
    const allDepsSucceeded = deps.every((depId) => {
      const depEntry = ledger[depId];
      return depEntry?.state === "SUCCEEDED" as NodeState;
    });
    if (allDepsSucceeded) {
      ready.push(nodeId);
      if (ready.length >= cap) break;
    }
  }
  return ready;
}

export function getMaxConcurrency(): number {
  const raw = process.env.READ_PLAN_EXECUTOR_MAX_CONCURRENCY;
  const parsed = raw ? parseInt(raw, 10) : 4;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 4;
}
