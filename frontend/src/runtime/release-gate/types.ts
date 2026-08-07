export type MaturityLevel = "L1" | "L2" | "L3";
export type ReleaseDecision =
  | "NO_RELEASE"
  | "L1_ONLY"
  | "L2_READ_COMPOSITION"
  | "L3_ACTION_GOVERNED";
export type ReleaseCaseStatus = "passed" | "failed" | "missing" | "skipped" | "stale";
export type ReleaseFixtureKind = "deterministic" | "recorded-llm" | "coordinator-e2e";

export type ReadContextMetricCounts = {
  contextConflictCases: number;
  falseSelects: number;
  nonReadyFrames: number;
  nonReadyGatewayCalls: number;
  callPlanSlotChecks: number;
  wrongCallPlanSlotRoles: number;
  duplicateTurnChecks: number;
  duplicateTurnGatewayCalls: number;
  casLeaseConflictChecks: number;
  stateOverwritesAfterConflict: number;
  staleFrameChecks: number;
  staleFrameExecutions: number;
  readWriteIsolationChecks: number;
  readContextWriteAuthorityCreations: number;
  deterministicCoreChecks: number;
  deterministicCorePassed: number;
  successfulRecoveryChecks: number;
  successfulRecoveries: number;
};

export type ReleaseMetricCounts = Partial<ReadContextMetricCounts> & {
  visibilityChecks: number;
  visibilityLeaks: number;
  writeApprovalChecks: number;
  writeApprovalBypasses: number;
  narrativeClaims: number;
  unsupportedNarrativeClaims: number;
  lineageRequired: number;
  lineageLinked: number;
};

export type ReleaseCaseResult = {
  caseId: string;
  level: MaturityLevel;
  stage: string;
  status: ReleaseCaseStatus;
  fixtureKind: ReleaseFixtureKind;
  evidenceRefs: string[];
  metrics: ReleaseMetricCounts;
  errorType?: string;
};

export type HardGateResult = { actual: number; required: number; passed: boolean };
export type ReleaseHardGates = {
  visibilityLeakageRate: HardGateResult;
  writeApprovalBypassRate: HardGateResult;
  unsupportedNarrativeClaimRate: HardGateResult;
  factLineageCompleteness: HardGateResult;
  falseSelectRate: HardGateResult;
  nonReadyGatewayCallRate: HardGateResult;
  wrongCallPlanSlotRoleRate: HardGateResult;
  duplicateTurnGatewayCallRate: HardGateResult;
  stateOverwriteAfterConflictRate: HardGateResult;
  staleFrameExecutionRate: HardGateResult;
  readContextWriteAuthorityCreationRate: HardGateResult;
  deterministicCorePassRate: HardGateResult;
  successfulRecoveryRate: HardGateResult;
};

export type ReleaseLevelResult = {
  profileVersion: string;
  denominator: number;
  casePassed: number;
  passed: boolean;
  hardGates: ReleaseHardGates;
  failures: Array<{ caseId: string; reason: string }>;
};

export type ReleaseReportMetadata = {
  codeVersion?: string;
  registrySnapshotId?: string;
  fixtureVersion?: string;
  modelRecordingVersion?: string;
  startedAt?: string;
  completedAt?: string;
};

export type ReleaseReport = {
  schema: "sap-nexus.agent-release-report.v1";
  codeVersion: string;
  registrySnapshotId: string;
  fixtureVersion: string;
  modelRecordingVersion: string;
  startedAt: string;
  completedAt: string;
  target: MaturityLevel;
  targetPassed: boolean;
  decision: ReleaseDecision;
  caseTotals: Record<ReleaseCaseStatus | "total", number>;
  levels: Record<MaturityLevel, ReleaseLevelResult>;
  caseResults: ReleaseCaseResult[];
  evidenceRefs: string[];
  liveSmoke: { status: "not_run" | "passed" | "failed"; environment?: string; evidenceRef?: string };
};
