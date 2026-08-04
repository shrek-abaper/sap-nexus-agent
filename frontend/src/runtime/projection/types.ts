import type { NodeState } from "../plan-executor/types";

export type ReasoningFact = {
  factId: string;
  agentTraceId: string;
  traceId: string;
  gatewayTraceId: string;
  domain: string;
  businessObject: string;
  predicate: string;
  value: number | null;
  unit: string | null;
  deterministic: boolean;
  confidence: number;
  source: Record<string, unknown>;
  evidence: Record<string, unknown>[];
  material: string | null;
  plant: string | null;
  asOf: string;
};

export type MissingFact = { factType: string; reason: string };

export type NodeLedgerSummary = {
  nodeId: string;
  state: NodeState;
  nodeExecutedAt?: string;
};

export type PlanExecutionRecord = {
  runId: string;
  snapshotId: string;
  nodeLedgerSummary: NodeLedgerSummary[];
  asOf: string;
  succeededNodes: string[];
  failedNodes: string[];
  missingFacts: MissingFact[];
};

export type SnapshotFact = ReasoningFact & { conflict?: boolean };

export type SnapshotLimitation = {
  kind:
    | "freshness_mismatch"
    | "unit_incompatibility"
    | "conflict"
    | "missing_optional"
    | "no_fact_builder";
  detail: string;
};

export type MaterialSupplySnapshot = {
  projectionId: string;
  projectionVersion: string;
  snapshotId: string;
  asOf: string;
  sourceFreshness: { nodeId: string; nodeExecutedAt: string; dataAsOf: string }[];
  completeness: "complete" | "partial" | "incomplete";
  facts: SnapshotFact[];
  lineage: { field: string; factId: string; evidence: Record<string, unknown> }[];
  missingFacts: MissingFact[];
  failedNodes: string[];
  limitations: SnapshotLimitation[];
  outputHash: string;
};

export type ProjectionInput = {
  planExecutionRecord: PlanExecutionRecord;
  facts: ReasoningFact[];
};

export type OutputProjectionDeclaration = {
  projectionId: string;
  version: string;
  requiredFactTypes: string[];
  optionalFactTypes: string[];
  outputSchema: string;
  timeBasis: "dataAsOf";
  partialPolicy: "complete-partial-incomplete";
  project(input: ProjectionInput): MaterialSupplySnapshot;
};

export type FactBuilderDeclaration<NodeRecord> = {
  capabilityId: string;
  freshnessField?: string;
  build(record: NodeRecord): ReasoningFact[];
};
