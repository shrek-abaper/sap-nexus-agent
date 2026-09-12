// Client-safe wire DTOs for the dsh conversation API. Kept independent of the
// server/dsh runtime (which imports server-only dsh packages).

export type DshFact = {
  ref: string;
  factId?: string;
  material: string | null;
  plant: string | null;
  value: number | null;
  unit: string | null;
  asOf: string;
  evidence?: unknown[];
};

export type DshCapability = {
  capabilityId: string;
  state: string;
  factRefs?: string[];
};

export type DshApprovalHandle = {
  approvalId: string;
  runId: string;
  expiresAt: string;
  capabilityId: string;
  parameters: Record<string, string>;
  factRefs: string[];
  hashes: { subjectHash: string; proposalHash: string; parameterSnapshotHash: string };
};

export type DshToolCall = {
  callId: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "completed" | "failed" | "awaiting_approval";
  result?: {
    status: string;
    runId: string;
    capabilityChain: DshCapability[];
    facts: DshFact[];
    narrative: { summary: string; limitations: string[] };
    limitations: string[];
    approval?: DshApprovalHandle;
    error?: { errorType: string; message: string };
  };
  error?: string;
};

export type DshTurnResponse = {
  conversationId: string;
  output: string;
  toolCalls: DshToolCall[];
  reasonKind?: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolCalls?: DshToolCall[];
  error?: string;
  pending?: boolean;
  /** Live model deltas before tools run (collapsed reasoning trace). */
  trace?: string;
  /** Live answer deltas after tools return (rendered in the bubble). */
  answerTrace?: string;
  /** Live tool cards while streaming. */
  liveTools?: DshToolCall[];
  /** True once the final answer arrived and the trace must collapse. */
  settled?: boolean;
};

export type ConversationSummary = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
};

export type StoredConversation = ConversationSummary & {
  messages: Array<ChatMessage & { ts?: number }>;
};

export type DshStreamEvent =
  | { type: "delta"; text: string; phase: "reasoning" | "answer" }
  | { type: "tool-start"; callId: string; name: string; args: unknown }
  | { type: "tool-result"; callId: string; name: string; status: DshToolCall["status"]; result?: unknown; error?: string }
  | { type: "final"; output: string; toolCalls: DshToolCall[]; reasonKind?: string }
  | { type: "error"; message: string };
