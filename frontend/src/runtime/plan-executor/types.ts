// frontend/src/runtime/plan-executor/types.ts

export const NodeState = {
  READY: "READY",
  VALIDATING: "VALIDATING",
  EXECUTING: "EXECUTING",
  SUCCEEDED: "SUCCEEDED",
  FAILED: "FAILED",
  TIMED_OUT: "TIMED_OUT",
  CANCELLED: "CANCELLED",
  BLOCKED_DEPENDENCY: "BLOCKED_DEPENDENCY",
  BLOCKED_APPROVAL: "BLOCKED_APPROVAL",
} as const;

export type NodeState = (typeof NodeState)[keyof typeof NodeState];

export type NodeLedgerEntry = {
  state: NodeState;
  attempt: number;
  inputHash: string;
  resultRef: string | null;
  traceSpan: string | null;
  updatedAt: string;
};

export type ParameterSource =
  | { kind: "literal"; semanticType: string; value: string }
  | { kind: "goalConstraint"; constraintName: string }
  | { kind: "factField"; producerNodeId: string; factTypeId: string; field: string };

export type ParameterBinding = {
  parameterName: string;
  source: ParameterSource;
};

export type PlanNodeV2 = {
  nodeId: string;
  capabilityId: string;
  parameterBindings: ParameterBinding[];
  producesFactTypes: string[];
  governance: { requiresApproval: boolean };
};

export type PlanEdgeV2 = {
  edgeId: string;
  kind: "data" | "dependency";
  fromNodeId: string;
  toNodeId: string;
  factTypeId?: string;
};

export type PlanGraphV2 = {
  planGraphVersion: number;
  planId: string;
  goalId: string;
  executionMode: string;
  snapshotId: string;
  nodes: PlanNodeV2[];
  edges: PlanEdgeV2[];
  topologicalOrder: string[];
  goalOutputs: { factTypeId: string; producerNodeId: string }[];
  readPartition: string[];
  actionPartition: string[];
  projectionRef: unknown[];
  ruleSetRefs: unknown[];
};

export type GatewayValidateResult = {
  valid: boolean;
  traceId?: string;
  errors?: string[];
};

export type GatewayExecuteResult = {
  success: boolean;
  traceId?: string;
  data?: Record<string, unknown>;
  errorType?: string;
  message?: string;
};

export interface GatewayClient {
  validate(capabilityId: string, parameters: Record<string, string>): Promise<GatewayValidateResult>;
  execute(capabilityId: string, parameters: Record<string, string>): Promise<GatewayExecuteResult>;
}

export type NodeFactRecord = {
  nodeId: string;
  agentTraceId: string;
  capabilityId: string;
  parameters: Record<string, string>;
  producesFactTypes: string[];
  gatewayTraceId: string | null;
  executeData: Record<string, unknown>;
  nodeExecutedAt: string;
};

export type PlanExecutorResult = {
  runId: string;
  snapshotId: string;
  nodeLedger: Record<string, NodeLedgerEntry>;
  succeeded: string[];
  succeededNodeResults: NodeFactRecord[];
  failed: string[];
  timedOut: string[];
  cancelled: string[];
  blocked: string[];
};
