export type RequiredDecisionConstraint =
  | "requiredQuantity"
  | "targetDate"
  | "purchasingGroup";

export type MaterialShortageRuleSet = {
  ruleSetId: string;
  version: string;
  registrySnapshotId: string;
  inputProjection: {
    projectionId: string;
    version: string;
  };
  requiredConstraints: RequiredDecisionConstraint[];
  maxProjectionAgeMs: number;
  actionCapabilityId: "MM.PR.CreateDraft";
  strategy: "material-shortage";
};

export type DecisionConstraints = {
  requiredQuantity?: number;
  targetDate?: string;
  purchasingGroup?: string;
};

export type DecisionActionCapability = {
  capabilityId: string;
  kind: "Action" | "Function";
  status: string;
  sideEffect: "sap_write" | "none";
  requiresApproval: boolean;
  approvalPolicy: "human_required" | "not_required";
  requiredParameters: string[];
};

export type DecisionRegistrySnapshot = {
  snapshotId: string;
  actionCapabilities: DecisionActionCapability[];
};

export type RuleSetRef = {
  ruleSetId: string;
  version: string;
};

export type RecommendationDecisionRequest = {
  registrySnapshot: DecisionRegistrySnapshot;
  projection: import("../projection/types").MaterialSupplySnapshot;
  ruleSetRef: RuleSetRef;
  constraints: DecisionConstraints;
  evaluatedAt: string;
};

export type RecommendationFact = {
  factId: string;
  predicate: string;
  value: number | null;
  unit: string | null;
  material: string | null;
  plant: string | null;
  asOf: string;
  source: Record<string, unknown>;
};

export type RecommendationLimitation = {
  code: string;
  detail: string;
  sourceRefs: string[];
};

export type RejectedAlternative = {
  code: string;
  reason: string;
  factIds: string[];
};

export type ParameterSource =
  | { kind: "constraint"; ref: RequiredDecisionConstraint }
  | { kind: "fact"; ref: string; field: string }
  | { kind: "rule"; ref: string };

export type ActionProposalParameters = {
  material: string;
  plant: string;
  quantity: number;
  unit: string;
  delivery_date: string;
  purchasing_group: string;
};

export type ActionProposal = {
  proposalId: string;
  snapshotId: string;
  projectionRef: RecommendationPlan["projectionRef"];
  capabilityId: "MM.PR.CreateDraft";
  status: "pending_approval";
  parameters: ActionProposalParameters;
  parameterSources: Record<keyof ActionProposalParameters, ParameterSource[]>;
  factsUsed: string[];
  ruleSetRefs: string[];
  proposalHash: string;
};

export type RecommendationPlan = {
  recommendationId: string;
  planHash: string;
  status: "RECOMMEND" | "NO_ACTION" | "CLARIFY" | "INSUFFICIENT_INPUT";
  summaryCode: string;
  snapshotId: string;
  projectionRef: {
    projectionId: string;
    version: string;
    outputHash: string;
  };
  ruleSetRefs: string[];
  facts: RecommendationFact[];
  rules: Array<{ ruleId: string; ruleSetRef: string; triggered: boolean }>;
  assumptions: string[];
  limitations: RecommendationLimitation[];
  rejectedAlternatives: RejectedAlternative[];
  actionProposal?: ActionProposal;
};
