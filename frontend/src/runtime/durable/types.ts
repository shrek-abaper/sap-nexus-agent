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
  schemaVersion?: 2;
  readState?: ConversationReadState | null;
};

export type SessionState = {
  lastContext: LastContext | null;
  lastRunId: string | null;
  history: Turn[];
  principalId?: string;
};

export type FrameStatus = "COLLECTING" | "READY" | "CONFLICTED" | "STALE";

export type SlotState = "RESOLVED" | "CONFLICTED" | "CLEARED";

export type SlotProvenance =
  | "EXPLICIT"
  | "CONFIRMED"
  | "INHERITED"
  | "MODEL_CANDIDATE"
  | "INHERITED_LEGACY";

export type SlotBinding = {
  name: string;
  value: string | null;
  candidates: string[];
  state: SlotState;
  provenance: SlotProvenance;
  sourceTurnId: string;
  sourceSpan: [number, number] | null;
  issues: string[];
};

export type ReadContextFrame = {
  frameId: string;
  capabilityId: string;
  slots: Record<string, SlotBinding>;
  status: FrameStatus;
  createdTurnId: string;
  updatedTurnId: string;
  registrySnapshotId: string;
  capabilityVersion: string;
};

export type PendingInteraction = {
  kind: "SLOT_CLARIFICATION" | "CAPABILITY_CHOICE" | "BATCH_CONFIRMATION" | "PLANNER_CONFIRMATION";
  frameId: string;
  expectedFields: string[];
  stateVersion: number;
  registrySnapshotId: string;
  expiresAt: string;
};

export type ConversationReadState = {
  activeFrame: ReadContextFrame | null;
  recentFrames: ReadContextFrame[];
  pendingInteraction: PendingInteraction | null;
  stateVersion: number;
};

export type ReadExecutionBinding = {
  turnId: string;
  frameId: string;
  stateVersion: number;
  registrySnapshotId: string;
  principalId: string;
  capabilityVersion: string;
  callPlanHash: string;
  readState: ConversationReadState;
};

export type SessionStateV2 = {
  schemaVersion: 2;
  stateVersion: number;
  principalId: string;
  activeFrame: ReadContextFrame | null;
  recentFrames: ReadContextFrame[];
  pendingInteraction: PendingInteraction | null;
  history: Turn[];
  lastAppliedTurnId: string | null;
  lastRunId: string | null;
};

export type ApprovalDecision = "approve" | "reject";

export type WorkbenchOutcome = {
  status: string;
  message?: string | null;
  responseText?: string | null;
  callPlan?: Record<string, unknown> | null;
  validationResult?: Record<string, unknown> | null;
  executionResult?: Record<string, unknown> | null;
  actionResult?: Record<string, unknown> | null;
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
  data?: Record<string, unknown>;
  parameters?: Record<string, string>;
  capabilityId?: string;
  producesFactTypes?: string[];
  nodeExecutedAt?: string;
  turnId?: string | null;
  frameId?: string | null;
  stateVersion?: number | null;
  registrySnapshotId?: string | null;
  conversationReadState?: ConversationReadState | null;
  resolutionReport?: Record<string, unknown> | null;
  decision?: Record<string, unknown> | null;
  readExecutionBinding?: ReadExecutionBinding | null;
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

export type ConversationLeaseOutcome =
  | { status: "claimed"; fenceToken: string; expiresAt: string }
  | { status: "rejected"; holder: string; expiresAt: string }
  | {
      status: "force-claimed";
      previousHolder: string;
      fenceToken: string;
      expiresAt: string;
    };

export type ConversationLeaseRenewal =
  | { status: "owned"; expiresAt: string }
  | { status: "lost"; holder?: string; expiresAt?: string };

export type ConversationCasOutcome =
  | { status: "saved"; stateVersion: number }
  | { status: "conflict"; actualVersion: number }
  | { status: "lease-lost"; holder?: string; expiresAt?: string };

export type ConversationLeaseFence = { workerId: string; fenceToken: string };

export type ConversationTurnLookup = { runId: string };

export type ConversationStoreErrorCode =
  | "CONTEXT_DESERIALIZATION_FAILED"
  | "CONTEXT_PRINCIPAL_MISMATCH"
  | "CONTEXT_INVALID_VERSION_TRANSITION"
  | "CONVERSATION_LEASE_INVALID";

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
  load(conversationId: string, principalId: string): Promise<SessionStateV2 | null>;
  claim(conversationId: string, workerId: string, ttlMs: number): Promise<ConversationLeaseOutcome>;
  compareAndSwap(
    conversationId: string,
    expectedVersion: number,
    next: SessionStateV2,
    leaseFence?: ConversationLeaseFence,
  ): Promise<ConversationCasOutcome>;
  renew(
    conversationId: string,
    workerId: string,
    fenceToken: string,
    ttlMs: number,
  ): Promise<ConversationLeaseRenewal>;
  release(conversationId: string, workerId: string, fenceToken: string): Promise<void>;
  lookupTurn(
    conversationId: string,
    principalId: string,
    turnId: string,
  ): Promise<ConversationTurnLookup | null>;
  clear(conversationId: string): Promise<void>;
  clearAll(): Promise<void>;
}
