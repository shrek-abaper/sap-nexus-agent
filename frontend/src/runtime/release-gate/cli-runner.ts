import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { evaluateRelease } from "./evaluator";
import {
  loadReleaseFixtures,
  runOfflineReleaseScenarios,
  type ScenarioOptions,
} from "./scenario-runner";
import type { MaturityLevel, ReleaseCaseResult, ReleaseReport } from "./types";

type ReleaseGateCliOptions = {
  repoRoot?: string;
  outputDirectory?: string;
  args?: string[];
  now?: () => string;
  codeVersion?: string;
  write?: (line: string) => void;
  runScenarios?: (options: ScenarioOptions) => Promise<ReleaseCaseResult[]>;
};

export type ReleaseGateCliResult = {
  exitCode: number;
  reportPath: string;
  report: ReleaseReport;
};

export async function runReleaseGateCli(
  options: ReleaseGateCliOptions = {},
): Promise<ReleaseGateCliResult> {
  const repoRoot = options.repoRoot ?? defaultRepoRoot();
  const outputDirectory = options.outputDirectory ?? path.join(repoRoot, "runtime/evals/results");
  const now = options.now ?? (() => new Date().toISOString());
  const write = options.write ?? ((line: string) => process.stdout.write(`${line}\n`));
  const target = parseTarget(options.args ?? process.argv.slice(2));
  const startedAt = now();
  const fixtures = loadReleaseFixtures(repoRoot);
  const results = await (options.runScenarios ?? runOfflineReleaseScenarios)({
    repoRoot,
    now: fixtures.scenarioClock,
    target,
  });
  const completedAt = now();
  const report = evaluateRelease(results, target, {
    codeVersion: options.codeVersion ?? currentCodeVersion(repoRoot),
    registrySnapshotId: "snapshot-release-gate",
    fixtureVersion: fixtures.caseVersion,
    modelRecordingVersion: fixtures.recordingVersion,
    startedAt,
    completedAt,
  });
  mkdirSync(outputDirectory, { recursive: true });
  const reportPath = path.join(
    outputDirectory,
    `agent-release-${target.toLowerCase()}-${safeTimestamp(startedAt)}.json`,
  );
  writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  write([
    `Release decision: ${report.decision}`,
    `target=${target}`,
    `passed=${report.targetPassed}`,
    `cases=${report.caseTotals.passed}/${report.caseTotals.total}`,
    "liveSmoke=not_run",
    `report=${path.relative(repoRoot, reportPath)}`,
  ].join(" | "));
  return { exitCode: report.targetPassed ? 0 : 1, reportPath, report };
}

function parseTarget(args: string[]): MaturityLevel {
  const index = args.indexOf("--profile");
  const raw = index >= 0 ? args[index + 1] : "all";
  if (raw === "all") return "L3";
  if (raw === "L1" || raw === "L2" || raw === "L3") return raw;
  throw new Error("--profile must be one of L1, L2, L3 or all");
}

function currentCodeVersion(repoRoot: string): string {
  try {
    return execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "unknown";
  }
}

function safeTimestamp(value: string): string {
  return value.replace(/[^0-9A-Za-z_-]/g, "-");
}

function defaultRepoRoot(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
}
