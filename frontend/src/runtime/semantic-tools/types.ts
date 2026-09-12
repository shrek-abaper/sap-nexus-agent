import type { JsonValue } from "../../shared/types/artifacts";

export const SEMANTIC_TOOL_CONTRACT_VERSION = 2 as const;
export const DIAGNOSE_MATERIAL_SUPPLY = "diagnose_material_supply" as const;
export const REVIEW_CUSTOMER_EXPOSURE = "review_customer_exposure" as const;
export const REVIEW_VENDOR_EXPOSURE = "review_vendor_exposure" as const;
export const PROPOSE_REPLENISHMENT = "propose_replenishment" as const;

export const SEMANTIC_TOOL_NAMES = [
  DIAGNOSE_MATERIAL_SUPPLY,
  REVIEW_CUSTOMER_EXPOSURE,
  REVIEW_VENDOR_EXPOSURE,
  PROPOSE_REPLENISHMENT,
] as const;

// v1 exposed only diagnose_material_supply; v2 adds the two READ exposure
// tools and the WRITE replenishment proposal.
export type SemanticToolName = (typeof SEMANTIC_TOOL_NAMES)[number];

export type SemanticToolStatus =
  | "complete"
  | "partial"
  | "clarification"
  | "out_of_scope"
  | "unavailable"
  | "rejected"
  | "awaiting_approval"
  | "failed";

export type SemanticToolRequest = {
  contractVersion: 1 | typeof SEMANTIC_TOOL_CONTRACT_VERSION;
  tool: SemanticToolName;
  utterance: string;
  slots?: {
    material?: string;
    plant?: string;
    customerNumber?: string;
    vendor?: string;
    companyCode?: string;
    requiredQuantity?: number;
    targetDate?: string;
    purchasingGroup?: string;
  };
  context?: {
    plantScope?: string;
    module?: "MM" | "SD" | "FI";
    periodHint?: string;
  };
  conversationId?: string;
};

export type ResolvedSemanticValue = {
  type: string;
  value: string;
  provenance: string;
};

export type CapabilityChainEntry = {
  capabilityId: string;
  state: string;
  factRefs?: string[];
};

export type SemanticToolFact = {
  ref: string;
  factId?: string;
  material: string | null;
  plant: string | null;
  value: number | null;
  unit: string | null;
  asOf: string;
  // LIST facts carry string-encoded quantities/amounts in evidence rows
  // (OData/JCO table extraction); numeric `value` may stay null.
  evidence?: JsonValue[];
};

// WRITE proposal handle: the dsh layer renders it, but the decision is made
// server-side via POST /api/agent-runs/[runId]/approval.
export type ApprovalHandle = {
  approvalId: string;
  runId: string;
  expiresAt: string;
  capabilityId: string;
  parameters: Record<string, string>;
  parameterSources?: Record<string, JsonValue>;
  factRefs: string[];
  hashes: {
    subjectHash: string;
    proposalHash: string;
    parameterSnapshotHash: string;
  };
};

export type SemanticToolResponse = {
  contractVersion: 1 | typeof SEMANTIC_TOOL_CONTRACT_VERSION;
  tool: SemanticToolName;
  status: SemanticToolStatus;
  runId: string;
  traceId?: string;
  resolved: { semanticValues: ResolvedSemanticValue[] };
  capabilityChain: CapabilityChainEntry[];
  facts: SemanticToolFact[];
  projection?: {
    ref: string;
    completeness: "complete" | "partial" | "incomplete";
    asOf: string;
    outputHash?: string;
    limitations: { kind?: string; detail?: string }[];
  };
  narrative: {
    summary: string;
    limitations: string[];
    evidenceRefs?: string[];
  };
  limitations: string[];
  approval?: ApprovalHandle;
  error?: { errorType: string; message: string };
};

export class SemanticToolRequestError extends Error {
  constructor(
    readonly errorType: string,
    message: string,
    readonly httpStatus: 400 | 404,
  ) {
    super(message);
    this.name = "SemanticToolRequestError";
  }
}

export class SemanticToolUpstreamError extends Error {
  constructor(
    readonly errorType: string,
    message: string,
    readonly httpStatus: 504,
  ) {
    super(message);
    this.name = "SemanticToolUpstreamError";
  }
}
