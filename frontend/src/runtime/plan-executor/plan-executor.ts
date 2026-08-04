// frontend/src/runtime/plan-executor/plan-executor.ts
import type { DurableRunStore } from "../durable/types";
import type { AgentRunEvent } from "../run-event-schema";
import type {
  GatewayClient,
  PlanGraphV2,
  PlanExecutorResult,
  NodeLedgerEntry,
  NodeState,
  ParameterBinding,
} from "./types";
import { NodeState as NS } from "./types";
import { assertTransition } from "./node-state-machine";
import { loadNodeLedger, transitionNode } from "./node-ledger";
import { selectReadyNodes, getMaxConcurrency } from "./dag-scheduler";
import { validatePlanGraphV2 } from "./plan-graph-v2-parser";
import { emitNodeStateChanged } from "./sse-emitter";

const LEASE_TTL_MS = 60_000;

export class PlanExecutor {
  private sequence: number = 2; // start after run_started (seq=1)
  // Serialize transition calls: transitionNode does a non-atomic read-modify-write
  // on the node ledger, so concurrent transitions for different nodes would
  // clobber each other. Gateway validate/execute calls remain concurrent.
  private transitionChain: Promise<void> = Promise.resolve();

  constructor(
    private readonly store: DurableRunStore,
    private readonly gateway: GatewayClient,
    private readonly workerId: string
  ) {}

  async execute(
    graph: PlanGraphV2,
    runId: string,
    expectedSnapshotId: string
  ): Promise<PlanExecutorResult> {
    // Step 2: validate + snapshot drift check (fail-closed)
    const validation = validatePlanGraphV2(graph, expectedSnapshotId);
    if (!validation.valid) {
      return this.emptyResult(runId, expectedSnapshotId);
    }

    // Step 3: claim run lease
    const leaseOutcome = await this.store.claim(runId, this.workerId, LEASE_TTL_MS);
    if (leaseOutcome.status === "rejected") {
      // lease conflict fail-closed
      return this.emptyResult(runId, expectedSnapshotId);
    }

    // Step 4: load existing node ledger (recovery)
    let ledger = await loadNodeLedger(this.store, runId);

    // Step 5-6: schedule + execute ready nodes
    const maxConcurrency = getMaxConcurrency();
    let pending = selectReadyNodes(graph, ledger, maxConcurrency);

    while (pending.length > 0) {
      const executing = pending.map(async (nodeId) => {
        await this.executeNode(graph, runId, expectedSnapshotId, nodeId, ledger);
      });
      await Promise.all(executing);
      // Reload ledger after execution round
      ledger = await loadNodeLedger(this.store, runId);
      pending = selectReadyNodes(graph, ledger, maxConcurrency);
    }

    // Build result from final ledger
    const finalLedger = await loadNodeLedger(this.store, runId);
    await this.store.release(runId, this.workerId);
    return this.buildResult(runId, expectedSnapshotId, finalLedger);
  }

  private async executeNode(
    graph: PlanGraphV2,
    runId: string,
    snapshotId: string,
    nodeId: string,
    ledger: Record<string, NodeLedgerEntry>
  ): Promise<void> {
    const node = graph.nodes.find((n) => n.nodeId === nodeId);
    if (!node) return;

    // Action / non-read-only node -> BLOCKED_APPROVAL
    if (node.governance.requiresApproval) {
      await this.transition(runId, snapshotId, nodeId, null, NS.BLOCKED_APPROVAL, 0, ledger);
      return;
    }

    // Already SUCCEEDED (skip on recovery)
    const existing = ledger[nodeId];
    if (existing?.state === NS.SUCCEEDED) return;

    const attempt = existing?.attempt ?? 0;
    const inputHash = this.computeInputHash(node.parameterBindings);

    // If node is not yet in READY (initial pickup or BLOCKED_DEPENDENCY cleared),
    // transition to READY first. The 9-state machine requires null/BLOCKED_DEPENDENCY
    // -> READY before READY -> VALIDATING.
    const priorState = existing?.state ?? null;
    if (priorState !== NS.READY) {
      await this.transition(runId, snapshotId, nodeId, priorState, NS.READY, attempt, ledger);
    }

    // READY -> VALIDATING
    await this.transition(runId, snapshotId, nodeId, NS.READY, NS.VALIDATING, attempt, ledger);

    // Resolve parameters
    const parameters = this.resolveParameters(node.parameterBindings);

    // Gateway validate
    const validateResult = await this.gateway.validate(node.capabilityId, parameters);
    if (!validateResult.valid) {
      // VALIDATING -> FAILED
      await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.FAILED, attempt, ledger);
      return;
    }

    // VALIDATING -> EXECUTING
    await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.EXECUTING, attempt, ledger);

    // Gateway execute
    const executeResult = await this.gateway.execute(node.capabilityId, parameters);
    if (!executeResult.success) {
      // EXECUTING -> FAILED
      await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.FAILED, attempt, ledger);
      return;
    }

    // EXECUTING -> SUCCEEDED
    await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.SUCCEEDED, attempt, ledger, executeResult.traceId ?? null);
  }

  private async transition(
    runId: string,
    snapshotId: string,
    nodeId: string,
    fromState: NodeState | null,
    toState: NodeState,
    attempt: number,
    ledger: Record<string, NodeLedgerEntry>,
    resultRef: string | null = null
  ): Promise<void> {
    // Acquire serialized lock (transitionNode read-modify-write is not atomic)
    const wait = this.transitionChain;
    let release!: () => void;
    this.transitionChain = new Promise<void>((r) => {
      release = r;
    });
    await wait;
    try {
      // Assert legal transition (fail-closed on illegal)
      assertTransition(fromState, toState);

      const entry: NodeLedgerEntry = {
        state: toState,
        attempt,
        inputHash: ledger[nodeId]?.inputHash ?? "",
        resultRef,
        traceSpan: null,
        updatedAt: new Date().toISOString(),
      };

      // Double-write: nodeState (authoritative) + events (audit/SSE)
      await transitionNode(this.store, runId, snapshotId, nodeId, entry);

      // Emit SSE event (coerce null -> "INITIAL" for string param, consistent with node-ledger)
      const emitFn = (event: AgentRunEvent) => {
        void this.store.appendEvent(runId, event);
      };
      const { nextSequence } = emitNodeStateChanged(emitFn, runId, nodeId, fromState ?? "INITIAL", toState, attempt, this.sequence);
      this.sequence = nextSequence;
    } finally {
      release();
    }
  }

  private resolveParameters(bindings: ParameterBinding[]): Record<string, string> {
    const params: Record<string, string> = {};
    for (const binding of bindings) {
      // Discriminated union on source.kind: only literal values are concrete;
      // goalConstraint / factField require upstream resolution deferred to an
      // enhanced executor. Non-literal bindings are skipped (not passed as
      // malformed values to the Gateway).
      if (binding.source.kind === "literal") {
        params[binding.parameterName] = binding.source.value;
      }
    }
    return params;
  }

  private computeInputHash(bindings: ParameterBinding[]): string {
    const sorted = bindings.map((b) => `${b.parameterName}`).sort().join(",");
    return `${sorted}`;
  }

  private emptyResult(runId: string, snapshotId: string): PlanExecutorResult {
    return {
      runId,
      snapshotId,
      nodeLedger: {},
      succeeded: [],
      failed: [],
      timedOut: [],
      cancelled: [],
      blocked: [],
    };
  }

  private buildResult(
    runId: string,
    snapshotId: string,
    ledger: Record<string, NodeLedgerEntry>
  ): PlanExecutorResult {
    const succeeded: string[] = [];
    const failed: string[] = [];
    const timedOut: string[] = [];
    const cancelled: string[] = [];
    const blocked: string[] = [];
    for (const [nodeId, entry] of Object.entries(ledger)) {
      switch (entry.state) {
        case NS.SUCCEEDED: succeeded.push(nodeId); break;
        case NS.FAILED: failed.push(nodeId); break;
        case NS.TIMED_OUT: timedOut.push(nodeId); break;
        case NS.CANCELLED: cancelled.push(nodeId); break;
        case NS.BLOCKED_DEPENDENCY:
        case NS.BLOCKED_APPROVAL: blocked.push(nodeId); break;
      }
    }
    return { runId, snapshotId, nodeLedger: ledger, succeeded, failed, timedOut, cancelled, blocked };
  }
}
