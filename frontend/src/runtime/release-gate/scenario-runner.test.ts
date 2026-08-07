import { describe, expect, it } from "vitest";
import path from "node:path";
import { evaluateRelease } from "./evaluator";
import { loadReleaseFixtures, runOfflineReleaseScenarios } from "./scenario-runner";

const repoRoot = path.resolve(process.cwd(), "..");

describe("offline release scenarios", () => {
  it("freezes all three fixture kinds per level and covers the required risk matrix", () => {
    const fixtures = loadReleaseFixtures(repoRoot);
    expect(fixtures.scenarioClock).toBe("2026-08-05T01:00:00.000Z");
    for (const level of ["L1", "L2", "L3"] as const) {
      expect(new Set(fixtures.cases.filter((entry) => entry.level === level)
        .map((entry) => entry.fixtureKind))).toEqual(new Set([
          "deterministic",
          "recorded-llm",
          "coordinator-e2e",
        ]));
    }
    const risks = new Set(fixtures.cases.flatMap((entry) => entry.riskTags));
    for (const risk of [
      "unknown-capability", "invisible-capability", "prompt-injection", "missing-parameter",
      "snapshot-drift", "node-timeout", "node-cancel", "node-recovery", "partial-fact",
      "freshness-mismatch", "missing-rule-input", "unsupported-claim", "approval-bypass", "hash-drift",
      "duplicate-continuation", "cross-principal", "sse-reconnect", "event-replay",
    ]) {
      expect(risks.has(risk)).toBe(true);
    }
    expect(fixtures.cases.every((entry) => entry.evidenceRequirements.length > 0)).toBe(true);
    expect(fixtures.recordings).toHaveLength(4);
    expect(fixtures.recordings.every((recording) => (
      recording.provider.length > 0
      && recording.model.length > 0
      && recording.promptVersion.length > 0
      && recording.responseSchema.length > 0
      && recording.recordedAt.length > 0
      && recording.version.length > 0
    ))).toBe(true);
    const contextCases = fixtures.cases.filter((entry) => entry.stage === "governed-read-context");
    expect(contextCases).toHaveLength(13);
    expect(contextCases.every((entry) => entry.fixtureKind === "deterministic"
      && entry.hardGateImpact.length > 0)).toBe(true);
    const badRecording = fixtures.recordings.find((entry) => entry.recordingId === "recording-context-bad");
    expect(badRecording).toMatchObject({
      redacted: true,
      normalizedResponse: {
        capabilityId: "MM.Inventory.GetAvailability",
        parameters: { material: "1000", plant: "工厂" },
      },
    });
    expect(JSON.stringify(fixtures)).not.toMatch(
      /"(?:credential|password|token|apiKey|rfcName|binding|url|sql|rawResponse|rawSapPayload)"\s*:/i,
    );
  });

  it("runs L1/L2/L3 offline through real Agent/coordinator boundaries", async () => {
    const results = await runOfflineReleaseScenarios({
      repoRoot,
      now: "2026-08-05T01:00:00.000Z",
    });
    const report = evaluateRelease(results, "L3", {
      codeVersion: "test-code",
      registrySnapshotId: "snapshot-release-gate",
      startedAt: "2026-08-05T01:00:00.000Z",
      completedAt: "2026-08-05T01:01:00.000Z",
    });

    expect(results).toHaveLength(22);
    expect(results.filter((result) => result.status !== "passed")).toEqual([]);
    expect(results.find((result) => result.caseId === "context-duplicate-turn-id")?.metrics)
      .toMatchObject({ duplicateTurnChecks: 1, duplicateTurnGatewayCalls: 0 });
    expect(results.find((result) => result.caseId === "context-concurrent-turns")?.metrics)
      .toMatchObject({ casLeaseConflictChecks: 2, stateOverwritesAfterConflict: 0 });
    expect(results.find((result) => result.caseId === "context-concurrent-turns")?.evidenceRefs)
      .toContain("durable:cas-conflict");
    expect(results.find((result) => result.caseId === "context-registry-drift")?.metrics)
      .toMatchObject({ staleFrameChecks: 1, staleFrameExecutions: 0 });
    expect(results.find((result) => result.caseId === "context-read-write-authority-isolation")?.metrics)
      .toMatchObject({ readWriteIsolationChecks: 1, readContextWriteAuthorityCreations: 0 });
    expect(results.filter((result) => result.fixtureKind === "coordinator-e2e")
      .every((result) => result.evidenceRefs.some((ref) => ref.startsWith("run:")))).toBe(true);
    expect(report.decision).toBe("L3_ACTION_GOVERNED");
    expect(report.liveSmoke.status).toBe("not_run");

    const repeated = await runOfflineReleaseScenarios({
      repoRoot,
      now: "2026-08-05T01:00:00.000Z",
    });
    expect(repeated).toEqual(results);
  }, 90_000);
});
