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

export type DshToolExchange = {
  request: {
    capabilityId: string;
    parameters: Record<string, string>;
  };
  response: {
    traceId?: string;
    executor?: { type?: string; rfcName?: string };
    success?: boolean;
    durationMs?: number;
    errorType?: string;
    returnMessages?: { type: string; id?: string; number?: string; message: string }[];
    data?: unknown;
  };
};

export type DshSemanticToolResult = {
  kind?: undefined;
  status: string;
  runId: string;
  capabilityChain: DshCapability[];
  facts: DshFact[];
  narrative: { summary: string; limitations: string[] };
  limitations: string[];
  exchange?: DshToolExchange;
  approval?: DshApprovalHandle;
  entityChoice?: DshEntityChoiceSet;
  error?: { errorType: string; message: string };
};

/** Client-safe mirror of the server EntityChoiceSet (durable/types). */
export type DshEntityChoiceSet = {
  candidateSetId: string;
  objectType: string;
  targetCapabilityId: string;
  targetSlot: string;
  snapshotId: string;
  sourceExtractedAt?: string | null;
  candidates: {
    index: number;
    canonicalCode: string;
    displayName: string;
    distinguishing: Record<string, string>;
    matchKind: string;
    status: "active" | "inactive";
    orgScopes: { field: string; value: string }[];
  }[];
};

// Client-safe mirrors of the server discovery tool responses (no server imports).
export type DshMasterDataDirectoryResult = {
  kind: "master-data-directory";
  status: string;
  objectType: string;
  candidates: {
    canonicalCode: string;
    displayName: string;
    matchKind: string;
    status: string;
    distinguishing: Record<string, string>;
    orgScopes: { field: string; value: string }[];
  }[];
  snapshotId?: string;
  resultCompleteness?: string;
  sourceExtractedAt?: string | null;
  narrative?: { summary: string; limitations: string[] };
  error?: { errorType: string; message: string };
};

export type DshCapabilityCatalogResult = {
  kind: "capability-catalog";
  status: string;
  capabilities: {
    capabilityId: string;
    name: string;
    description: string;
    domain: string;
    sideEffect: string;
    requiresApproval: boolean;
    requiredInputs: string[];
  }[];
  snapshotId?: string;
  narrative?: { summary: string; limitations: string[] };
  error?: { errorType: string; message: string };
};

// Client-safe mirror of the server OntologyAnalysisToolResponse (no server imports).
export type DshOntologyField = { value: string; semanticType: string };
export type DshOntologyToolResult = {
  kind: "ontology-analysis";
  contractVersion?: number;
  tool?: string;
  status: string;
  runId: string;
  facts: {
    factTypeRef: string;
    fields: Record<string, DshOntologyField>;
    unit: { field: string; value: string } | null;
  }[];
  results?: {
    nodeId: string;
    operatorId: string;
    status: string;
    rows: Record<string, unknown>[];
  }[];
  gaps?: string[];
  limitations?: string[];
  writeGatewayCalls?: number;
  narrative?: { summary: string; limitations: string[] };
  error?: { errorType: string; message: string };
};

export type DshToolCall = {
  callId: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "completed" | "failed" | "awaiting_approval";
  result?: DshSemanticToolResult | DshOntologyToolResult
    | DshMasterDataDirectoryResult | DshCapabilityCatalogResult;
  error?: string;
};

export type DshTurnResponse = {
  conversationId: string;
  output: string;
  toolCalls: DshToolCall[];
  reasonKind?: string;
};

export type MessageFeedback = {
  rating: "up" | "down";
  note?: string;
  ts?: number;
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
  /** Send/store time of the message; drives the hover clock label. */
  ts?: number;
  /** Wall time of the turn, filled when the final answer arrives. */
  runMs?: number;
  /** Latest persisted feedback for this message, if any. */
  feedback?: MessageFeedback;
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
  /** Emitted by the stream route after the turn is persisted: the
   * store-assigned message ids that feedback/branch actions reference. */
  | { type: "persisted"; userMessageId: string; assistantMessageId: string }
  | { type: "error"; message: string };
