// frontend/src/runtime/plan-executor/sse-emitter.ts
import type { AgentRunEvent } from "../run-event-schema";
import type { NodeState } from "./types";

type EmitFn = (event: AgentRunEvent) => void;

export function emitNodeStateChanged(
  emit: EmitFn,
  runId: string,
  nodeId: string,
  fromState: string,
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
    fromState,
    toState,
    attempt,
  };
  emit(event);
  return { event, nextSequence: sequence + 1 };
}
