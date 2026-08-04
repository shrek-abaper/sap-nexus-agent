// frontend/src/runtime/plan-executor/sse-emitter.ts
import type { AgentRunEvent } from "../run-event-schema";
import type { NodeState } from "./types";

type EmitFn = (event: AgentRunEvent) => void;

export function emitNodeStateChanged(
  emit: EmitFn,
  runId: string,
  nodeId: string,
  fromState: NodeState | null,
  toState: NodeState,
  attempt: number,
  sequence: number
): { event: AgentRunEvent; nextSequence: number } {
  const event: AgentRunEvent = {
    runId,
    sequence,
    timestamp: new Date().toISOString(),
    type: "node_state_changed",
    state: "running",
    nodeId,
    // AgentRunEvent.fromState is typed as string | undefined, but the SSE
    // contract requires null for initial transitions. The schema field should
    // be `string | null` (Task 4 schema gap); cast bridges the mismatch.
    fromState: (fromState ?? null) as string | undefined,
    toState,
    attempt,
  };
  emit(event);
  return { event, nextSequence: sequence + 1 };
}
