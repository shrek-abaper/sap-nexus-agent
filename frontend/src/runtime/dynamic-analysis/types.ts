/**
 * Wire types for the ontology-governed dynamic read analysis path (C2).
 * These mirror schemas/{typed-fact,analysis-result}.schema.json and the
 * analysis runtime stdin/stdout envelope. Measures are decimal strings.
 */

export type AnalysisStatus =
  | "complete"
  | "partial"
  | "clarification"
  | "capability_gap"
  | "semantic_gap"
  | "rejected"
  | "failed";

export interface AnalysisWireInput {
  wireVersion: 1;
  runId?: string;
  release: {
    semanticSnapshotId: string;
    registrySnapshotId: string;
  };
  nodeResults: ReadNodeResult[];
  analysisPlan: {
    nodes: AnalysisPlanNode[];
    outputs: string[];
  };
  requestedConclusions: {
    id: string;
    statement: string;
    evidenceRequirement?: string;
  }[];
}

export interface ReadNodeResult {
  nodeId: string;
  capabilityId: string;
  parameters: Record<string, string>;
  gatewayTraceId: string | null;
  executedAt: string;
  data: Record<string, unknown>;
}

export interface AnalysisPlanNode {
  nodeId: string;
  operatorId: "select_fields" | "filter_eq" | "group_sum" | "compare";
  operatorVersion?: string;
  inputs: Array<
    | { kind: "factField"; factTypeId: string; field: string }
    | { kind: "nodeRef"; nodeId: string }
  >;
  params: Record<string, unknown>;
  definitionRefs?: string[];
  dependsOn: string[];
}

export interface TypedFieldValue {
  value: string;
  semanticType: string;
}

export interface TypedFact {
  schemaVersion: 1;
  factId: string;
  factTypeRef: string;
  objectType: string;
  objectKey: Record<string, string>;
  scope: Record<string, string>;
  rowIdentity: Record<string, string>;
  fields: Record<string, TypedFieldValue>;
  unit: { field: string; value: string } | null;
  businessTime: string | null;
  collectedAt: string;
  definitionRef: string | null;
  evidence: {
    runId: string;
    nodeId: string;
    gatewayTraceId: string | null;
    rawFields: string[];
    completeness: string;
  };
}

export interface AnalysisResultRow {
  groupKey?: Record<string, unknown>;
  measures?: Record<string, { decimal: string; unit: string }>;
  fields?: Record<string, TypedFieldValue>;
  lineage?: string[];
  [key: string]: unknown;
}

export interface AnalysisResult {
  schemaVersion: 1;
  nodeId: string;
  operatorId: string;
  status: AnalysisStatus;
  outputType: "rows" | "groupedRows" | "comparison";
  rows: AnalysisResultRow[];
  excludedRows: { factId: string; reason: string }[];
  operatorVersion: string;
  definitionRefs: string[];
  partial: boolean;
  limits: Record<string, unknown>;
  reasons: string[];
}

export interface AnalysisWireOutput {
  wireVersion: 1;
  status: AnalysisStatus;
  facts: TypedFact[];
  results: AnalysisResult[];
  uncoveredConclusions: { conclusionId: string; reason: string }[];
  limits: Record<string, unknown>;
  semanticSnapshotId: string;
  excludedRows?: { factId: string; reason: string }[];
  conflicts?: string[];
  normalizationExclusions?: { factId: string; reason: string }[];
}
