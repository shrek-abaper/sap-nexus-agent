import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { MaturityLevel, ReleaseCaseResult } from "./types";
import { runReleaseGateCli } from "./cli-runner";

const directories: string[] = [];
const NOW = "2026-08-05T09:00:00.000Z";

afterEach(() => {
  for (const directory of directories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("release gate CLI", () => {
  it("writes a complete redacted report for the requested continuous profile", async () => {
    const outputDirectory = temporaryDirectory();
    const stdout: string[] = [];
    let scenarioNow = "";
    const result = await runReleaseGateCli({
      repoRoot: path.resolve(process.cwd(), ".."),
      outputDirectory,
      args: ["--profile", "all"],
      now: () => NOW,
      codeVersion: "test-code",
      write: (line) => stdout.push(line),
      runScenarios: async (options) => {
        scenarioNow = options.now;
        return [passing("l1", "L1"), passing("l2", "L2"), passing("l3", "L3")];
      },
    });

    const report = JSON.parse(readFileSync(result.reportPath, "utf8"));
    expect(result.exitCode).toBe(0);
    expect(report).toMatchObject({
      schema: "sap-nexus.agent-release-report.v1",
      codeVersion: "test-code",
      registrySnapshotId: "snapshot-release-gate",
      target: "L3",
      targetPassed: true,
      decision: "L3_ACTION_GOVERNED",
      caseTotals: { total: 3, passed: 3 },
      liveSmoke: { status: "not_run" },
    });
    expect(report.caseResults).toHaveLength(3);
    expect(scenarioNow).toBe("2026-08-05T01:00:00.000Z");
    expect(stdout.join("\n")).toContain("L3_ACTION_GOVERNED");
    expect(JSON.stringify(report)).not.toMatch(/credential|rawSapPayload|rawResponse/i);
  });

  it("returns nonzero and preserves the lower passing decision when the target fails", async () => {
    const outputDirectory = temporaryDirectory();
    const failedL3 = { ...passing("l3", "L3"), status: "failed" as const, errorType: "HASH_DRIFT" };
    const result = await runReleaseGateCli({
      repoRoot: path.resolve(process.cwd(), ".."),
      outputDirectory,
      args: ["--profile", "L3"],
      now: () => NOW,
      codeVersion: "test-code",
      write: () => {},
      runScenarios: async () => [passing("l1", "L1"), passing("l2", "L2"), failedL3],
    });

    expect(result.exitCode).toBe(1);
    expect(result.report.decision).toBe("L2_READ_COMPOSITION");
    expect(result.report.levels.L3.failures).toEqual([{ caseId: "l3", reason: "HASH_DRIFT" }]);
  });
});

function passing(caseId: string, level: MaturityLevel): ReleaseCaseResult {
  return {
    caseId,
    level,
    stage: level === "L1" ? "single-capability" : level === "L2" ? "composition" : "action",
    status: "passed",
    fixtureKind: "coordinator-e2e",
    evidenceRefs: [`run:${caseId}`],
    metrics: {
      visibilityChecks: 1,
      visibilityLeaks: 0,
      writeApprovalChecks: level === "L3" ? 1 : 0,
      writeApprovalBypasses: 0,
      narrativeClaims: 1,
      unsupportedNarrativeClaims: 0,
      lineageRequired: 1,
      lineageLinked: 1,
    },
  };
}

function temporaryDirectory(): string {
  const directory = mkdtempSync(path.join(tmpdir(), "sap-nexus-release-cli-"));
  directories.push(directory);
  return directory;
}
