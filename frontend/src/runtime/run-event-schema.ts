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
  | "run_failed";

export type AgentRunState =
  | "idle"
  | "submitting"
  | "running"
  | "intent_parsed"
  | "capability_selected"
  | "callplan_created"
  | "approval_checked"
  | "awaiting_approval"
  | "rejected"
  | "validating"
  | "executing"
  | "fact_created"
  | "narrated"
  | "trace_linked"
  | "completed"
  | "failed";

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
  hitlState?: HumanInTheLoopState;
  artifact?: RedactedArtifact;
  error?: {
    errorType: string;
    message: string;
    stage: AgentRunState;
  };
};

export type AgentRunSnapshot = {
  runId: string;
  state: AgentRunState;
  hitlState: HumanInTheLoopState;
  events: AgentRunEvent[];
  latestArtifact?: RedactedArtifact;
  error?: AgentRunEvent["error"];
};
