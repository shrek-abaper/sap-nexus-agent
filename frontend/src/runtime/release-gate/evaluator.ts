import { MATURITY_LEVELS, RELEASE_PROFILE_VERSIONS } from "./profiles";
import type {
  MaturityLevel,
  ReleaseCaseResult,
  ReleaseCaseStatus,
  ReleaseDecision,
  ReleaseHardGates,
  HardGateResult,
  ReleaseLevelResult,
  ReleaseMetricCounts,
  ReleaseReport,
  ReleaseReportMetadata,
} from "./types";

const DECISIONS: Record<number, ReleaseDecision> = {
  0: "NO_RELEASE",
  1: "L1_ONLY",
  2: "L2_READ_COMPOSITION",
  3: "L3_ACTION_GOVERNED",
};

// Canonical governed-read-context case IDs (`runner: "governed-read-context"`
// in evals/end_to_end_agent_release_cases.json). Used only to detect whether
// `evaluateRelease` is evaluating the full, real governed-read-context
// fixture set for a level (as opposed to a synthetic/partial result list
// built in a unit test), so the aggregate evidence-total gate below applies
// only to genuine full runs and never perturbs isolated gate tests.
const CONTEXT_CASE_IDS: readonly string[] = [
  "context-direct-plant-switch",
  "context-clear-then-ambiguous-reference",
  "context-explicit-correction",
  "context-llm-unavailable",
  "context-malformed-json",
  "context-technical-override-injection",
  "context-capability-switch",
  "context-recent-frame-explicit-restoration",
  "context-registry-drift",
  "context-principal-mismatch",
  "context-concurrent-turns",
  "context-duplicate-turn-id",
  "context-read-write-authority-isolation",
];

// Expected SUMMED totals of these three metrics across ALL 13 context-*
// cases. `contextConflictCases`, `nonReadyFrames`, and `callPlanSlotChecks`
// are populated generically by `contextMetrics()` in scenario-runner.ts for
// every context-* case (unlike their four sibling metrics, each of which has
// exactly one dedicated producer case), so a single-case backstop cannot
// cover them. These constants were verified empirically -- not derived from
// any run's own denominator -- by running
// `npm --prefix frontend run release-gate -- --profile all` and inspecting
// the per-case `metrics` in the resulting
// runtime/evals/results/agent-release-l3-*.json (identical totals confirmed
// across the 2026-08-07T06-12-17-202Z, 2026-08-07T06-33-34-114Z, and
// 2026-08-07T07-59-23-472Z runs) on 2026-08-07. Any single case's evidence
// silently regressing to 0 changes one of these totals away from the
// expected value regardless of whether other cases still pass.
const EXPECTED_CONTEXT_AGGREGATE_TOTALS = {
  contextConflictCases: 9,
  nonReadyFrames: 10,
  callPlanSlotChecks: 20,
} as const;

export function evaluateRelease(
  results: ReleaseCaseResult[],
  target: MaturityLevel,
  metadata: ReleaseReportMetadata = {},
): ReleaseReport {
  const levels = {} as Record<MaturityLevel, ReleaseLevelResult>;
  let continuousPass = true;
  let highestPassing = 0;
  for (const [index, level] of MATURITY_LEVELS.entries()) {
    const selected = results.filter((result) => result.level === level);
    const hasFullContextCaseSet = CONTEXT_CASE_IDS.every((caseId) =>
      selected.some((result) => result.caseId === caseId));
    const gates = hardGates(sumMetrics(selected), hasFullContextCaseSet);
    const failures = selected
      .flatMap((result) => {
        const contextEvidenceError = requiredContextEvidenceError(result);
        if (result.status === "passed" && result.evidenceRefs.length > 0 && !contextEvidenceError) {
          return [];
        }
        return [{
          caseId: result.caseId,
          reason: contextEvidenceError ?? result.errorType
            ?? (result.evidenceRefs.length === 0 ? "EVIDENCE_MISSING" : result.status.toUpperCase()),
        }];
      });
    const ownPassed = selected.length > 0
      && failures.length === 0
      && Object.values(gates).every((gate) => gate.passed);
    continuousPass = continuousPass && ownPassed;
    levels[level] = {
      profileVersion: RELEASE_PROFILE_VERSIONS[level],
      denominator: selected.length,
      casePassed: selected.filter((result) => (
        result.status === "passed"
        && result.evidenceRefs.length > 0
        && !requiredContextEvidenceError(result)
      )).length,
      passed: continuousPass,
      hardGates: gates,
      failures,
    };
    if (continuousPass) highestPassing = index + 1;
  }

  const statuses: ReleaseCaseStatus[] = ["passed", "failed", "missing", "skipped", "stale"];
  const totals = Object.fromEntries(statuses.map((status) => [
    status,
    results.filter((result) => result.status === status).length,
  ])) as Record<ReleaseCaseStatus, number>;
  const now = new Date().toISOString();
  return {
    schema: "sap-nexus.agent-release-report.v1",
    codeVersion: metadata.codeVersion ?? "unknown",
    registrySnapshotId: metadata.registrySnapshotId ?? "unknown",
    fixtureVersion: metadata.fixtureVersion ?? "1.0.0",
    modelRecordingVersion: metadata.modelRecordingVersion ?? "1.0.0",
    startedAt: metadata.startedAt ?? now,
    completedAt: metadata.completedAt ?? now,
    target,
    targetPassed: levels[target].passed,
    decision: DECISIONS[highestPassing],
    caseTotals: { total: results.length, ...totals },
    levels,
    caseResults: results.map((result) => ({
      ...result,
      evidenceRefs: [...result.evidenceRefs],
      metrics: { ...result.metrics },
    })),
    evidenceRefs: [...new Set(results.flatMap((result) => result.evidenceRefs))].sort(),
    liveSmoke: { status: "not_run" },
  };
}

function sumMetrics(results: ReleaseCaseResult[]): ReleaseMetricCounts {
  return results.reduce<ReleaseMetricCounts>((total, result) => ({
    visibilityChecks: total.visibilityChecks + result.metrics.visibilityChecks,
    visibilityLeaks: total.visibilityLeaks + result.metrics.visibilityLeaks,
    writeApprovalChecks: total.writeApprovalChecks + result.metrics.writeApprovalChecks,
    writeApprovalBypasses: total.writeApprovalBypasses + result.metrics.writeApprovalBypasses,
    narrativeClaims: total.narrativeClaims + result.metrics.narrativeClaims,
    unsupportedNarrativeClaims: total.unsupportedNarrativeClaims + result.metrics.unsupportedNarrativeClaims,
    lineageRequired: total.lineageRequired + result.metrics.lineageRequired,
    lineageLinked: total.lineageLinked + result.metrics.lineageLinked,
    contextConflictCases: (total.contextConflictCases ?? 0) + (result.metrics.contextConflictCases ?? 0),
    falseSelects: (total.falseSelects ?? 0) + (result.metrics.falseSelects ?? 0),
    nonReadyFrames: (total.nonReadyFrames ?? 0) + (result.metrics.nonReadyFrames ?? 0),
    nonReadyGatewayCalls: (total.nonReadyGatewayCalls ?? 0) + (result.metrics.nonReadyGatewayCalls ?? 0),
    callPlanSlotChecks: (total.callPlanSlotChecks ?? 0) + (result.metrics.callPlanSlotChecks ?? 0),
    wrongCallPlanSlotRoles: (total.wrongCallPlanSlotRoles ?? 0) + (result.metrics.wrongCallPlanSlotRoles ?? 0),
    duplicateTurnChecks: (total.duplicateTurnChecks ?? 0) + (result.metrics.duplicateTurnChecks ?? 0),
    duplicateTurnGatewayCalls: (total.duplicateTurnGatewayCalls ?? 0) + (result.metrics.duplicateTurnGatewayCalls ?? 0),
    casLeaseConflictChecks: (total.casLeaseConflictChecks ?? 0) + (result.metrics.casLeaseConflictChecks ?? 0),
    stateOverwritesAfterConflict: (total.stateOverwritesAfterConflict ?? 0) + (result.metrics.stateOverwritesAfterConflict ?? 0),
    staleFrameChecks: (total.staleFrameChecks ?? 0) + (result.metrics.staleFrameChecks ?? 0),
    staleFrameExecutions: (total.staleFrameExecutions ?? 0) + (result.metrics.staleFrameExecutions ?? 0),
    readWriteIsolationChecks: (total.readWriteIsolationChecks ?? 0) + (result.metrics.readWriteIsolationChecks ?? 0),
    readContextWriteAuthorityCreations: (total.readContextWriteAuthorityCreations ?? 0) + (result.metrics.readContextWriteAuthorityCreations ?? 0),
    deterministicCoreChecks: (total.deterministicCoreChecks ?? 0) + (result.metrics.deterministicCoreChecks ?? 0),
    deterministicCorePassed: (total.deterministicCorePassed ?? 0) + (result.metrics.deterministicCorePassed ?? 0),
    successfulRecoveryChecks: (total.successfulRecoveryChecks ?? 0) + (result.metrics.successfulRecoveryChecks ?? 0),
    successfulRecoveries: (total.successfulRecoveries ?? 0) + (result.metrics.successfulRecoveries ?? 0),
  }), {
    visibilityChecks: 0,
    visibilityLeaks: 0,
    writeApprovalChecks: 0,
    writeApprovalBypasses: 0,
    narrativeClaims: 0,
    unsupportedNarrativeClaims: 0,
    lineageRequired: 0,
    lineageLinked: 0,
    contextConflictCases: 0,
    falseSelects: 0,
    nonReadyFrames: 0,
    nonReadyGatewayCalls: 0,
    callPlanSlotChecks: 0,
    wrongCallPlanSlotRoles: 0,
    duplicateTurnChecks: 0,
    duplicateTurnGatewayCalls: 0,
    casLeaseConflictChecks: 0,
    stateOverwritesAfterConflict: 0,
    staleFrameChecks: 0,
    staleFrameExecutions: 0,
    readWriteIsolationChecks: 0,
    readContextWriteAuthorityCreations: 0,
    deterministicCoreChecks: 0,
    deterministicCorePassed: 0,
    successfulRecoveryChecks: 0,
    successfulRecoveries: 0,
  });
}

function hardGates(metrics: ReleaseMetricCounts, requireExactContextTotals: boolean): ReleaseHardGates {
  const zeroGate = (
    numerator: number,
    denominator: number,
    applicable = false,
    requiredDenominator?: number,
  ) => {
    const actual = denominator === 0 ? 0 : numerator / denominator;
    // When `requiredDenominator` is set (only for a full context-case-set
    // evaluation), the denominator must match it EXACTLY: unlike the
    // `applicable` (`denominator > 0`) check, this can't be satisfied by a
    // denominator that silently regressed to a smaller-but-still-positive
    // value while its numerator regressed to 0 alongside it.
    const denominatorOk = requiredDenominator === undefined
      ? (!applicable || denominator > 0)
      : denominator === requiredDenominator;
    return { actual, required: 0, passed: actual === 0 && denominatorOk };
  };
  const completeness = metrics.lineageRequired === 0
    ? 1
    : metrics.lineageLinked / metrics.lineageRequired;
  return {
    visibilityLeakageRate: zeroGate(metrics.visibilityLeaks, metrics.visibilityChecks),
    writeApprovalBypassRate: zeroGate(metrics.writeApprovalBypasses, metrics.writeApprovalChecks),
    unsupportedNarrativeClaimRate: zeroGate(
      metrics.unsupportedNarrativeClaims,
      metrics.narrativeClaims,
    ),
    factLineageCompleteness: {
      actual: completeness,
      required: 1,
      passed: completeness === 1,
    },
    falseSelectRate: zeroGate(
      metrics.falseSelects ?? 0,
      metrics.contextConflictCases ?? 0,
      (metrics.contextConflictCases ?? 0) > 0,
      requireExactContextTotals ? EXPECTED_CONTEXT_AGGREGATE_TOTALS.contextConflictCases : undefined,
    ),
    nonReadyGatewayCallRate: zeroGate(
      metrics.nonReadyGatewayCalls ?? 0,
      metrics.nonReadyFrames ?? 0,
      (metrics.nonReadyFrames ?? 0) > 0,
      requireExactContextTotals ? EXPECTED_CONTEXT_AGGREGATE_TOTALS.nonReadyFrames : undefined,
    ),
    wrongCallPlanSlotRoleRate: zeroGate(
      metrics.wrongCallPlanSlotRoles ?? 0,
      metrics.callPlanSlotChecks ?? 0,
      (metrics.callPlanSlotChecks ?? 0) > 0,
      requireExactContextTotals ? EXPECTED_CONTEXT_AGGREGATE_TOTALS.callPlanSlotChecks : undefined,
    ),
    duplicateTurnGatewayCallRate: zeroGate(
      metrics.duplicateTurnGatewayCalls ?? 0,
      metrics.duplicateTurnChecks ?? 0,
      (metrics.duplicateTurnChecks ?? 0) > 0,
    ),
    stateOverwriteAfterConflictRate: zeroGate(
      metrics.stateOverwritesAfterConflict ?? 0,
      metrics.casLeaseConflictChecks ?? 0,
      (metrics.casLeaseConflictChecks ?? 0) > 0,
    ),
    staleFrameExecutionRate: zeroGate(
      metrics.staleFrameExecutions ?? 0,
      metrics.staleFrameChecks ?? 0,
      (metrics.staleFrameChecks ?? 0) > 0,
    ),
    readContextWriteAuthorityCreationRate: zeroGate(
      metrics.readContextWriteAuthorityCreations ?? 0,
      metrics.readWriteIsolationChecks ?? 0,
      (metrics.readWriteIsolationChecks ?? 0) > 0,
    ),
    deterministicCorePassRate: completeRate(
      metrics.deterministicCorePassed ?? 0,
      metrics.deterministicCoreChecks ?? 0,
      (metrics.contextConflictCases ?? 0) > 0,
    ),
    successfulRecoveryRate: completeRate(
      metrics.successfulRecoveries ?? 0,
      metrics.successfulRecoveryChecks ?? 0,
      (metrics.contextConflictCases ?? 0) > 0,
    ),
  };
}

function requiredContextEvidenceError(result: ReleaseCaseResult): string | null {
  const required: Record<string, ReadonlyArray<readonly [keyof ReleaseMetricCounts, number]>> = {
    "context-duplicate-turn-id": [["duplicateTurnChecks", 1]],
    "context-concurrent-turns": [["casLeaseConflictChecks", 2]],
    "context-registry-drift": [["staleFrameChecks", 1]],
    "context-read-write-authority-isolation": [["readWriteIsolationChecks", 1]],
    // NOTE: contextConflictCases / nonReadyFrames / callPlanSlotChecks are
    // actually populated by EVERY context-* case (verified empirically;
    // `evals/end_to_end_agent_release_cases.json` `hardGateImpact`
    // annotations do not reliably identify the contributing cases -- see
    // EXPECTED_CONTEXT_AGGREGATE_TOTALS above). These four per-case entries
    // are kept as an extra backstop for these specific cases/values (and to
    // preserve their existing regression test coverage in isolation), but
    // the primary protection against a silent evidence regression in ANY of
    // the 13 context-* cases is the exact-total aggregate check in
    // `hardGates()`, gated by `hasFullContextCaseSet`.
    "context-clear-then-ambiguous-reference": [
      ["contextConflictCases", 2],
      ["callPlanSlotChecks", 2],
    ],
    "context-llm-unavailable": [["nonReadyFrames", 1]],
    "context-malformed-json": [["nonReadyFrames", 1]],
    "context-capability-switch": [["callPlanSlotChecks", 3]],
  };
  const requirements = required[result.caseId];
  if (!requirements) return null;
  for (const [metric, expected] of requirements) {
    if (result.metrics[metric] !== expected) return `CONTEXT_EVIDENCE_MISSING:${metric}`;
  }
  return null;
}

function completeRate(passed: number, checks: number, required: boolean): HardGateResult {
  const actual = checks === 0 ? 0 : passed / checks;
  return { actual, required: 1, passed: !required || (checks > 0 && actual === 1) };
}
