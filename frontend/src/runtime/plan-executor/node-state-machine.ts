// frontend/src/runtime/plan-executor/node-state-machine.ts
import { NodeState } from "./types";

type StateOrNull = NodeState | null;

const LEGAL_TRANSITIONS: Record<string, NodeState[]> = {
  [NodeState.BLOCKED_DEPENDENCY]: [NodeState.READY, NodeState.CANCELLED],
  [NodeState.BLOCKED_APPROVAL]: [NodeState.CANCELLED],
  [NodeState.READY]: [NodeState.VALIDATING, NodeState.CANCELLED],
  [NodeState.VALIDATING]: [NodeState.EXECUTING, NodeState.FAILED, NodeState.TIMED_OUT, NodeState.CANCELLED],
  [NodeState.EXECUTING]: [NodeState.SUCCEEDED, NodeState.FAILED, NodeState.TIMED_OUT, NodeState.CANCELLED],
  [NodeState.FAILED]: [NodeState.READY],
  [NodeState.TIMED_OUT]: [NodeState.READY],
  [NodeState.SUCCEEDED]: [],
  [NodeState.CANCELLED]: [],
};

const INITIAL_STATES: NodeState[] = [
  NodeState.READY,
  NodeState.BLOCKED_DEPENDENCY,
  NodeState.BLOCKED_APPROVAL,
  NodeState.CANCELLED,
];

export function isLegalTransition(from: StateOrNull, to: NodeState): boolean {
  if (from === null) return INITIAL_STATES.includes(to);
  const allowed = LEGAL_TRANSITIONS[from];
  return allowed ? allowed.includes(to) : false;
}

export class IllegalTransitionError extends Error {
  constructor(
    public readonly fromState: NodeState | null,
    public readonly toState: NodeState
  ) {
    super(`illegal node state transition: ${fromState ?? "INITIAL"} -> ${toState}`);
    this.name = "IllegalTransitionError";
  }
}

export function assertTransition(from: StateOrNull, to: NodeState): void {
  if (!isLegalTransition(from, to)) {
    throw new IllegalTransitionError(from, to);
  }
}
