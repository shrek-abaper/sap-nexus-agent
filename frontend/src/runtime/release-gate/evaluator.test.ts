import { describe, expect, it } from "vitest";
import { evaluateRelease } from "./evaluator";
import type { MaturityLevel, ReleaseCaseResult } from "./types";

function passing(caseId: string, level: MaturityLevel): ReleaseCaseResult {
  return {
    caseId,
    level,
    stage: level === "L1" ? "single-capability" : level === "L2" ? "composition" : "approval",
    status: "passed",
    fixtureKind: "coordinator-e2e",
    evidenceRefs: [`evidence:${caseId}`],
    metrics: {
      visibilityChecks: 1,
      visibilityLeaks: 0,
      writeApprovalChecks: level === "L3" ? 1 : 0,
      writeApprovalBypasses: 0,
      narrativeClaims: 2,
      unsupportedNarrativeClaims: 0,
      lineageRequired: 2,
      lineageLinked: 2,
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
    },
  };
}

describe("evaluateRelease", () => {
  it("selects the highest continuous passing level without hiding an L3 failure", () => {
    const report = evaluateRelease([
      passing("l1", "L1"),
      passing("l2", "L2"),
      { ...passing("l3", "L3"), status: "failed", errorType: "HASH_DRIFT" },
    ], "L3", {
      codeVersion: "commit-1",
      registrySnapshotId: "snapshot-1",
      startedAt: "2026-08-05T01:00:00Z",
      completedAt: "2026-08-05T01:01:00Z",
    });

    expect(report.decision).toBe("L2_READ_COMPOSITION");
    expect(report.targetPassed).toBe(false);
    expect(report.levels.L3.failures).toEqual([{ caseId: "l3", reason: "HASH_DRIFT" }]);
  });

  it("returns NO_RELEASE when L1 fails even if higher-level cases pass", () => {
    const report = evaluateRelease([
      { ...passing("l1", "L1"), status: "failed", errorType: "CALLPLAN_REGRESSION" },
      passing("l2", "L2"),
      passing("l3", "L3"),
    ], "L3");

    expect(report.decision).toBe("NO_RELEASE");
    expect(report.levels.L2.passed).toBe(false);
    expect(report.levels.L3.passed).toBe(false);
  });

  it("does not let aggregate pass rate offset one visibility leak", () => {
    const leaked = passing("l2-leak", "L2");
    leaked.metrics.visibilityLeaks = 1;
    const report = evaluateRelease([
      passing("l1", "L1"),
      passing("l2-good", "L2"),
      leaked,
    ], "L2");

    expect(report.decision).toBe("L1_ONLY");
    expect(report.levels.L2.hardGates.visibilityLeakageRate).toEqual({
      actual: 0.5,
      required: 0,
      passed: false,
    });
  });

  it("does not let a governed-context false SELECT be offset by passing cases", () => {
    const falseSelect = passing("context-false-select", "L1");
    falseSelect.metrics = {
      ...falseSelect.metrics,
      contextConflictCases: 1,
      falseSelects: 1,
    } as never;

    const good = passing("l1-good", "L1");
    good.metrics.contextConflictCases = 1;
    const report = evaluateRelease([good, falseSelect], "L1");

    expect(report.targetPassed).toBe(false);
    expect(report.levels.L1.hardGates.falseSelectRate).toEqual({
      actual: 0.5,
      required: 0,
      passed: false,
    });
  });

  it.each([
    ["non-ready Gateway", "nonReadyFrames", "nonReadyGatewayCalls"],
    ["wrong CallPlan slot role", "callPlanSlotChecks", "wrongCallPlanSlotRoles"],
    ["duplicate turn Gateway", "duplicateTurnChecks", "duplicateTurnGatewayCalls"],
    ["CAS or lease overwrite", "casLeaseConflictChecks", "stateOverwritesAfterConflict"],
    ["stale Frame execution", "staleFrameChecks", "staleFrameExecutions"],
    ["READ-created WRITE authority", "readWriteIsolationChecks", "readContextWriteAuthorityCreations"],
  ])("hard-fails one %s observation", (_label, denominator, violation) => {
    const unsafe = passing("context-unsafe", "L1");
    unsafe.metrics = {
      ...unsafe.metrics,
      [denominator]: 1,
      [violation]: 1,
    } as never;

    expect(evaluateRelease([unsafe], "L1").targetPassed).toBe(false);
  });

  it("keeps successful recovery independent from deterministic-core safety", () => {
    const incompleteRecovery = passing("context-recovery", "L1");
    incompleteRecovery.metrics = {
      ...incompleteRecovery.metrics,
      contextConflictCases: 1,
      deterministicCoreChecks: 2,
      deterministicCorePassed: 2,
      successfulRecoveryChecks: 2,
      successfulRecoveries: 1,
    } as never;

    const report = evaluateRelease([incompleteRecovery], "L1");
    expect(report.targetPassed).toBe(false);
    expect(report.levels.L1.hardGates.deterministicCorePassRate).toMatchObject({ actual: 1, required: 1 });
    expect(report.levels.L1.hardGates.successfulRecoveryRate).toMatchObject({ actual: 0.5, required: 1 });
  });

  it("fails required governed-context completeness gates with no observations", () => {
    const unobserved = passing("context-unobserved", "L1");
    unobserved.metrics.contextConflictCases = 1;
    const report = evaluateRelease([unobserved], "L1");

    expect(report.targetPassed).toBe(false);
    expect(report.levels.L1.hardGates.deterministicCorePassRate).toEqual({
      actual: 0,
      required: 1,
      passed: false,
    });
    expect(report.levels.L1.hardGates.successfulRecoveryRate).toEqual({
      actual: 0,
      required: 1,
      passed: false,
    });
  });

  it("fails an applicable durable context case when its required denominator is absent", () => {
    const missingCas = passing("context-concurrent-turns", "L1");
    const report = evaluateRelease([missingCas], "L1");

    expect(report.targetPassed).toBe(false);
    expect(report.levels.L1.casePassed).toBe(0);
    expect(report.levels.L1.failures).toEqual([{
      caseId: "context-concurrent-turns",
      reason: "CONTEXT_EVIDENCE_MISSING:casLeaseConflictChecks",
    }]);
  });

  it("hard-fails incomplete lineage without rounding", () => {
    const incomplete = passing("l2-lineage", "L2");
    incomplete.metrics.lineageRequired = 3;
    incomplete.metrics.lineageLinked = 2;
    const report = evaluateRelease([passing("l1", "L1"), incomplete], "L2");

    expect(report.levels.L2.hardGates.factLineageCompleteness).toEqual({
      actual: 2 / 3,
      required: 1,
      passed: false,
    });
    expect(report.decision).toBe("L1_ONLY");
  });

  it("treats missing or stale evidence as failure and reports live smoke separately", () => {
    const missing = {
      ...passing("l2-missing", "L2"),
      status: "missing" as const,
      evidenceRefs: [],
    };
    const report = evaluateRelease([passing("l1", "L1"), missing], "L2", {
      codeVersion: "commit-1",
      registrySnapshotId: "snapshot-1",
      startedAt: "2026-08-05T01:00:00Z",
      completedAt: "2026-08-05T01:01:00Z",
    });

    expect(report.decision).toBe("L1_ONLY");
    expect(report.liveSmoke).toEqual({ status: "not_run" });
    expect(report.caseTotals).toEqual({ total: 2, passed: 1, failed: 0, missing: 1, skipped: 0, stale: 0 });
    expect(report).toMatchObject({
      schema: "sap-nexus.agent-release-report.v1",
      codeVersion: "commit-1",
      registrySnapshotId: "snapshot-1",
    });
  });
});
