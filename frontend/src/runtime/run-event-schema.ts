import type { RedactedArtifact } from "../shared/types/artifacts";

export type AgentRunEventType =
  | "run_started"
  | "intent_parsed"
  | "capability_selected"
  | "callplan_created"
  | "approval_state_changed"
  | "gateway_validate_started"
  | "gateway_validate_completed"
  | "gateway_execute_started"
  | "gateway_execute_completed"
  | "reasoning_fact_created"
  | "narrative_created"
  | "trace_linked"
  | "run_completed"
  | "run_failed"
  | "match_decision_created"
  | "batch_confirm_requested"
  | "node_state_changed"
  | "intent_recognized"
  | "capability_recalled"
  | "plan_compiled"
  | "plan_node_state"
  | "fact_emitted"
  | "projection_completed"
  | "recommendation_completed"
  | "narrative_completed"
  | "action_proposed"
  | "approval_updated"
  | "action_executed";

export type AgentRunState =
  | "idle"
  | "submitting"
  | "running"
  | "intent_parsed"
  | "capability_selected"
  | "callplan_created"
  | "approval_checked"
  | "awaiting_approval"
  | "awaiting_batch_confirm"
  | "rejected"
  | "validating"
  | "executing"
  | "fact_created"
  | "narrated"
  | "trace_linked"
  | "completed"
  | "failed"
  | "match_decided";

export type HumanInTheLoopState =
  | "approval_not_required"
  | "approval_required"
  | "awaiting_human_approval"
  | "approved"
  | "rejected"
  | "expired";

export type AgentRunEvent = {
  runId: string;
  sequence: number;
  timestamp: string;
  type: AgentRunEventType;
  state: AgentRunState;
  capabilityId?: string;
  agentTraceId?: string;
  gatewayTraceId?: string;
  traceId?: string;
  snapshotId?: string;
  objectRefs?: Array<{ kind: string; ref: string }>;
  hitlState?: HumanInTheLoopState;
  artifact?: RedactedArtifact;
  error?: {
    errorType: string;
    message: string;
    stage: AgentRunState;
  };
  // node_state_changed: plan-graph node transition audit fields (SSE replay)
  nodeId?: string;
  fromState?: string;
  toState?: string;
  attempt?: number;
};

export type AgentRunSnapshot = {
  runId: string;
  state: AgentRunState;
  hitlState: HumanInTheLoopState;
  events: AgentRunEvent[];
  latestArtifact?: RedactedArtifact;
  error?: AgentRunEvent["error"];
  replayIntegrity?: {
    status: "consistent" | "gap" | "conflict";
    expectedSequence?: number;
    receivedSequence?: number;
    message?: string;
  };
};
