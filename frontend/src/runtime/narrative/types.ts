import type { MaterialSupplySnapshot, ReasoningFact } from "../projection/types";
import type { RecommendationPlan } from "../recommendation/types";

export type NarrativeLocale = "zh-CN" | "en";

export type NarrativeProposalStatus =
  | "none"
  | "pending_approval"
  | "approved"
  | "executed"
  | "failed";

export type NarrativeProposalState = {
  status: NarrativeProposalStatus;
  proposalId?: string;
  stateRef: string;
};

export type NarrativeSourceInput = {
  locale: NarrativeLocale;
  facts: ReasoningFact[];
  projection: MaterialSupplySnapshot;
  recommendation: RecommendationPlan;
  proposalState: NarrativeProposalState;
};

export type NarrativeSourceKind =
  | "fact"
  | "projection"
  | "recommendation"
  | "rule"
  | "proposal_state";

export type NarrativeContentItem = {
  claimId: string;
  sourceKind: NarrativeSourceKind;
  sourceRef: string;
  evidenceRefs: string[];
  templateText: string;
};

export type NarrativeLimitation = {
  code: string;
  detail: string;
  evidenceRefs: string[];
};

export type NarrativeInputProjection = {
  locale: NarrativeLocale;
  completeness: MaterialSupplySnapshot["completeness"];
  items: NarrativeContentItem[];
  limitations: NarrativeLimitation[];
  recommendationRef: string;
  proposalRef: string | null;
  approvalState: NarrativeProposalStatus;
  stateEvidenceRef: string;
};

export type NarrativeClaim = {
  claimId: string;
  text: string;
  sourceRef: string;
  evidenceRefs: string[];
};

export type NarrativeEnvelope = {
  summary: string;
  claims: NarrativeClaim[];
  evidenceRefs: string[];
  limitations: NarrativeLimitation[];
  recommendationRef: string;
  proposalRef: string | null;
  approvalState: NarrativeProposalStatus;
  completeness: MaterialSupplySnapshot["completeness"];
  templateFallbackUsed: boolean;
};

export type NarrativePrompt = {
  system: string;
  user: string;
};

export interface NarrativeModel {
  generateJson(prompt: NarrativePrompt): Promise<string>;
}

export type NarrativeGenerationOptions = {
  timeoutMs?: number;
};

export type NarrativeGroundingMetrics = {
  totalClaims: number;
  groundedClaims: number;
  unsupportedClaims: number;
  claimGroundingRate: number;
  unsupportedClaimRate: number;
};
