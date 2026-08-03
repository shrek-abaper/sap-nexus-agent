import type { AgentRunEvent, AgentRunState } from "../run-event-schema";

// --- Shared runtime types (extracted from agent-runtime-adapter.ts) ---

export type LastContext = {
  capabilityId: string;
  parameters: Record<string, string>;
  missingParameters: string[];
  decisionType: "CLARIFY" | "SELECT";
};

export type Turn = { role: "user" | "assistant"; content: string };

export type ConversationContext = {
  lastContext: LastContext | null;
  history: Turn[] | null;
};

export type SessionState = {
  lastContext: LastContext | null;
  lastRunId: string | null;
  history: Turn[];
  principalId?: string;
};

export type ApprovalDecision = "approve" | "reject";

export type WorkbenchOutcome = {
  status: string;
  message?: string | null;
  responseText?: string | null;
  callPlan?: Record<string, unknown> | null;
  validationResult?: Record<string, unknown> | null;
  executionResult?: Record<string, unknown> | null;
  fact?: Record<string, unknown> | null;
  gatewayTraceId?: string | null;
  errorType?: string | null;
  missingParameters?: string[] | null;
  approvalRecord?: Record<string, unknown> | null;
  combinations?: Record<string, string>[] | null;
  matchDecision?: Record<string, unknown> | null;
  dryRun?: Record<string, unknown> | null;
  plannerFailure?: Record<string, unknown> | null;
  lastContext?: LastContext | null;
};

export type AgentRunRecord = {
  runId: string;
  query: string;
  events: AgentRunEvent[];
  pendingOutcome?: WorkbenchOutcome;
  decision?: ApprovalDecision;
  principalId: string;
};

// --- Durable store data structures ---

export type LeaseOutcome =
  | { status: "claimed" }
  | { status: "rejected"; holder: string; expiresAt: string }
  | { status: "force-claimed"; previousHolder: string };

export type CheckpointRef = {
  registrySnapshotId: string;
  nodeState: Record<string, unknown>;
  approvalRecordRef?: string | null;
};

export type ContinuationType =
  | "approval_approve"
  | "approval_reject"
  | "batch_confirm";

// --- JSONL line types (run event log, discriminated by `kind`) ---

export type RunJsonlLine =
  | { kind: "run_meta"; runId: string; query: string; principalId?: string }
  | ({ kind: "event" } & AgentRunEvent)
  | { kind: "pending_outcome"; value: WorkbenchOutcome }
  | { kind: "decision"; value: ApprovalDecision }
  | { kind: "checkpoint_ref"; value: CheckpointRef };

// --- Store-agnostic interfaces (core; extended in Task 6/7/8) ---

export interface DurableRunStore {
  save(runId: string, record: AgentRunRecord): Promise<void>;
  load(runId: string): Promise<AgentRunRecord | null>;
  list(filter?: { state?: AgentRunState; principalId?: string }): Promise<AgentRunRecord[]>;
  appendEvent(runId: string, event: AgentRunEvent): Promise<void>;
  appendPendingOutcome(runId: string, outcome: WorkbenchOutcome): Promise<void>;
  appendDecision(runId: string, decision: ApprovalDecision): Promise<void>;
  clearAll(): Promise<void>;
  claim(runId: string, workerId: string, ttlMs: number): Promise<LeaseOutcome>;
  release(runId: string, workerId: string): Promise<void>;
  renew(runId: string, workerId: string, ttlMs: number): Promise<void>;
  appendCheckpointRef(runId: string, ref: CheckpointRef): Promise<void>;
  loadCheckpointRef(runId: string): Promise<CheckpointRef | null>;
  markExecuted(key: string, result: WorkbenchOutcome): Promise<void>;
  lookupExecuted(key: string): Promise<WorkbenchOutcome | null>;
}

export interface DurableConversationStore {
  save(conversationId: string, state: SessionState): Promise<void>;
  load(conversationId: string, principalId?: string): Promise<SessionState | null>;
  clear(conversationId: string): Promise<void>;
  clearAll(): Promise<void>;
}
