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
const DEFAULT_NODE_TIMEOUT_MS = 30_000;

const TERMINAL_STATES: string[] = [
  NS.SUCCEEDED,
  NS.FAILED,
  NS.TIMED_OUT,
  NS.CANCELLED,
];

type PlanExecutorOptions = {
  nodeTimeoutMs?: number;
  sseBroadcast?: (event: AgentRunEvent) => void;
};

export class PlanExecutor {
  private sequence: number = 2; // start after run_started (seq=1)
  // Serialize transition calls: transitionNode does a non-atomic read-modify-write
  // on the node ledger, so concurrent transitions for different nodes would
  // clobber each other. Gateway validate/execute calls remain concurrent.
  private transitionChain: Promise<void> = Promise.resolve();
  private cancelled: boolean = false;
  private readonly nodeTimeoutMs: number;
  private readonly sseBroadcast: (event: AgentRunEvent) => void;

  constructor(
    private readonly store: DurableRunStore,
    private readonly gateway: GatewayClient,
    private readonly workerId: string,
    optionsOrBroadcast?: PlanExecutorOptions | ((event: AgentRunEvent) => void)
  ) {
    if (typeof optionsOrBroadcast === "function") {
      this.sseBroadcast = optionsOrBroadcast;
      this.nodeTimeoutMs = DEFAULT_NODE_TIMEOUT_MS;
    } else {
      this.sseBroadcast = optionsOrBroadcast?.sseBroadcast ?? (() => {});
      this.nodeTimeoutMs = optionsOrBroadcast?.nodeTimeoutMs ?? DEFAULT_NODE_TIMEOUT_MS;
    }
  }

  cancel(): void {
    this.cancelled = true;
  }

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

    try {
      // Step 4: load existing node ledger (recovery)
      let ledger = await loadNodeLedger(this.store, runId);

      // Step 5-6: schedule + execute ready nodes
      const maxConcurrency = getMaxConcurrency();
      let pending = selectReadyNodes(graph, ledger, maxConcurrency);

      while (pending.length > 0 && !this.cancelled) {
        const executing = pending.map(async (nodeId) => {
          await this.executeNode(graph, runId, expectedSnapshotId, nodeId, ledger);
        });
        await Promise.all(executing);
        // Reload ledger after execution round
        ledger = await loadNodeLedger(this.store, runId);
        pending = selectReadyNodes(graph, ledger, maxConcurrency);
      }

      // If cancelled, mark all non-terminal nodes as CANCELLED.
      // SUCCEEDED nodes are preserved (terminal state, skipped here).
      if (this.cancelled) {
        for (const nodeId of graph.readPartition) {
          const entry = ledger[nodeId];
          if (entry && !TERMINAL_STATES.includes(entry.state)) {
            await this.transition(runId, expectedSnapshotId, nodeId, entry.state as NodeState, NS.CANCELLED, entry.attempt, entry.inputHash);
          }
        }
      }

      // Mark read-partition nodes that were never selected (prerequisite did
      // not SUCCEED, e.g. partial failure) as BLOCKED_DEPENDENCY. These nodes
      // have no ledger entry because selectReadyNodes skipped them every round.
      // Skipped when cancelled: the cancel sweep above (or pre-existing
      // terminal states) already accounts for those nodes.
      if (!this.cancelled) {
        for (const nodeId of graph.readPartition) {
          if (ledger[nodeId]) continue;
          const node = graph.nodes.find((n) => n.nodeId === nodeId);
          const inputHash = node ? this.computeInputHash(node.parameterBindings) : "";
          await this.transition(runId, expectedSnapshotId, nodeId, null, NS.BLOCKED_DEPENDENCY, 0, inputHash);
        }
      }

      // Build result from final ledger
      const finalLedger = await loadNodeLedger(this.store, runId);
      return this.buildResult(runId, expectedSnapshotId, finalLedger);
    } finally {
      await this.store.release(runId, this.workerId);
    }
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

    const inputHash = this.computeInputHash(node.parameterBindings);

    // Action / non-read-only node -> BLOCKED_APPROVAL
    if (node.governance.requiresApproval) {
      await this.transition(runId, snapshotId, nodeId, null, NS.BLOCKED_APPROVAL, 0, inputHash);
      return;
    }

    // Already SUCCEEDED (skip on recovery)
    const existing = ledger[nodeId];
    if (existing?.state === NS.SUCCEEDED) return;

    const attempt = existing?.attempt ?? 0;

    // Idempotency key = runId + nodeId + attempt + inputHash (Task 10)
    const idempotencyKey = `${runId}:${nodeId}:${attempt}:${inputHash}`;
    const cachedResult = await this.store.lookupExecuted(idempotencyKey);

    // If node is not yet in READY (initial pickup or BLOCKED_DEPENDENCY cleared),
    // transition to READY first. The 9-state machine requires null/BLOCKED_DEPENDENCY
    // -> READY before READY -> VALIDATING.
    const priorState = existing?.state ?? null;

    // Check cancel before starting (post-loop marking handles un-ledgered nodes)
    if (this.cancelled) return;

    if (priorState !== NS.READY) {
      await this.transition(runId, snapshotId, nodeId, priorState, NS.READY, attempt, inputHash);
    }

    // READY -> VALIDATING
    await this.transition(runId, snapshotId, nodeId, NS.READY, NS.VALIDATING, attempt, inputHash);

    if (cachedResult) {
      // Idempotent replay: skip Gateway validate/execute, transition to SUCCEEDED
      // using the recorded result (validates -> executing -> succeeded)
      await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.EXECUTING, attempt, inputHash);
      await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.SUCCEEDED, attempt, inputHash, cachedResult.gatewayTraceId ?? null);
      return;
    }

    // Resolve parameters
    const parameters = this.resolveParameters(node.parameterBindings);

    // Gateway validate
    const validateResult = await this.gateway.validate(node.capabilityId, parameters);
    if (!validateResult.valid) {
      // VALIDATING -> FAILED
      await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.FAILED, attempt, inputHash);
      return;
    }

    // Check cancel before execute (VALIDATING -> CANCELLED is legal)
    if (this.cancelled) {
      await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.CANCELLED, attempt, inputHash);
      return;
    }

    // VALIDATING -> EXECUTING
    await this.transition(runId, snapshotId, nodeId, NS.VALIDATING, NS.EXECUTING, attempt, inputHash);

    // Gateway execute with node-level timeout
    const executeResult = await this.gatewayExecuteWithTimeout(node.capabilityId, parameters);
    if (executeResult.timedOut) {
      // EXECUTING -> TIMED_OUT (doesn't block independent nodes)
      await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.TIMED_OUT, attempt, inputHash);
      return;
    }
    if (!executeResult.success) {
      // EXECUTING -> FAILED
      await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.FAILED, attempt, inputHash);
      return;
    }

    // EXECUTING -> SUCCEEDED
    await this.transition(runId, snapshotId, nodeId, NS.EXECUTING, NS.SUCCEEDED, attempt, inputHash, executeResult.traceId ?? null);

    // Record idempotency: future replay with same key skips Gateway calls (Task 10)
    await this.store.markExecuted(idempotencyKey, {
      status: "succeeded",
      gatewayTraceId: executeResult.traceId ?? null,
    });
  }

  private async transition(
    runId: string,
    snapshotId: string,
    nodeId: string,
    fromState: NodeState | null,
    toState: NodeState,
    attempt: number,
    inputHash: string,
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
        inputHash,
        resultRef,
        traceSpan: null,
        updatedAt: new Date().toISOString(),
      };

      // Double-write: nodeState (authoritative) + events (audit/SSE)
      await transitionNode(this.store, runId, snapshotId, nodeId, entry);

      // Live SSE push only (in-memory subscriber broadcast).
      // The durable node_state_changed event is appended exactly once by
      // transitionNode above (Task 4 spec-required dual-write).
      const emitFn = (event: AgentRunEvent) => this.sseBroadcast(event);
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
    // Hash resolved parameter VALUES (what is actually sent to the Gateway),
    // not parameter names. Same inputs -> same hash; different inputs -> different hash.
    const params = this.resolveParameters(bindings);
    const entries = Object.entries(params).sort(([a], [b]) => a.localeCompare(b));
    return entries.map(([k, v]) => `${k}=${v}`).join("&");
  }

  private async gatewayExecuteWithTimeout(
    capabilityId: string,
    parameters: Record<string, string>
  ): Promise<{ success: boolean; data?: Record<string, unknown>; errorType?: string; timedOut: boolean; traceId?: string }> {
    try {
      const result = await Promise.race([
        this.gateway.execute(capabilityId, parameters),
        this.timeoutPromise(this.nodeTimeoutMs),
      ]);
      if (result === "TIMEOUT") return { success: false, timedOut: true, errorType: "TIMEOUT" };
      return { success: result.success, data: result.data, errorType: result.errorType, timedOut: false, traceId: result.traceId };
    } catch {
      return { success: false, timedOut: false };
    }
  }

  private timeoutPromise(ms: number): Promise<"TIMEOUT"> {
    return new Promise((resolve) => setTimeout(() => resolve("TIMEOUT"), ms));
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
