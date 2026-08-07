import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  PlanActionContinuation,
  type ActionGateway,
  type ActionGatewayRequest,
} from "../action-governance/action-governance";
import { CompositionCoordinator } from "../composition/coordinator";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import { JsonlConversationStore } from "../durable/jsonl-conversation-store";
import { canonicalJson, sha256Hex } from "../durable/canonical-json";
import {
  createAgentRun,
  setDurableStoresForTests,
  setReadAgentRunnerForTests,
} from "../agent-runtime-adapter";
import type { AgentRunRecord } from "../durable/types";
import type { WorkbenchOutcome } from "../durable/types";
import { FakeGateway } from "../plan-executor/fake-gateway";
import type { PlanGraphV2 } from "../plan-executor/types";
import { PLACEHOLDER_PRINCIPAL } from "../principal/types";
import { applyRunEvent, createInitialSnapshot } from "../run-state-machine";
import type {
  MaturityLevel,
  ReleaseCaseResult,
  ReleaseFixtureKind,
  ReleaseMetricCounts,
} from "./types";

type FixtureRunner =
  | "fixture-contract"
  | "recorded-intent"
  | "python-agent-eval"
  | "governed-read-context"
  | "composition-e2e"
  | "action-e2e";

export type ReleaseCaseFixture = {
  caseId: string;
  level: MaturityLevel;
  stage: string;
  fixtureKind: ReleaseFixtureKind;
  runner: FixtureRunner;
  recordingId?: string;
  expectedOutcome: "passed";
  evidenceRequirements: string[];
  hardGateImpact: string[];
  riskTags: string[];
};

export type RecordedLlmFixture = {
  recordingId: string;
  provider: string;
  model: string;
  promptVersion: string;
  responseSchema: string;
  recordedAt: string;
  version: string;
  redacted: boolean;
  normalizedResponse: {
    decisionType: string;
    capabilityIds: string[];
    capabilityId?: string;
    parameters?: Record<string, string>;
  };
};

export type ReleaseFixtureBundle = {
  profileVersion: string;
  scenarioClock: string;
  caseVersion: string;
  recordingVersion: string;
  cases: ReleaseCaseFixture[];
  recordings: RecordedLlmFixture[];
};

export type ScenarioOptions = { repoRoot: string; now: string; target?: MaturityLevel };

const SNAPSHOT_ID = "snapshot-release-gate";
const VISIBLE_CAPABILITIES = new Set([
  "MM.Inventory.GetAvailability",
  "MM.PurchaseOrder.GetList",
  "MM.PR.CreateDraft",
]);
const FORBIDDEN_KEYS = new Set([
  "credential", "credentials", "password", "token", "apikey", "rfcname",
  "binding", "url", "sql", "rawresponse", "rawsappayload",
]);
type ContextTurnEvidence = {
  turnId: string;
  recordingId: string | null;
  stateBefore: Record<string, unknown> | null;
  stateAfter: Record<string, unknown>;
  frame: { status: string };
  slots: Record<string, { value: string | null; state: string; role: string }>;
  decision: string;
  callPlan: {
    capabilityId: string;
    parameters: Record<string, string>;
    slotRoles: Record<string, string>;
  } | null;
  validateDelta: number;
  executeDelta: number;
  writeAuthority: { approvalRecord: boolean; selectionBinding: boolean };
  workbenchOutcome: WorkbenchOutcome;
  continuation: { status: string; errorType: string | null; workbenchOutcome: WorkbenchOutcome } | null;
};

type ContextCaseEvidence = {
  caseId: string;
  fixtureVersion: string;
  registrySnapshotId: string;
  status: "passed" | "failed";
  turns: ContextTurnEvidence[];
  failureRefs: Array<Record<string, unknown>>;
};

const governedContextEvalCache = new Map<string, Promise<Map<string, ContextCaseEvidence>>>();
const durableContextEvalCache = new Map<string, Promise<Map<string, Partial<ReleaseMetricCounts>>>>();
let runtimeProtocolDirectory: string | null = null;

export function loadReleaseFixtures(repoRoot: string): ReleaseFixtureBundle {
  const profilePayload = readJson<Record<string, unknown>>(
    path.join(repoRoot, "evals/end_to_end_agent_release_profiles.json"),
  );
  const casePayload = readJson<Record<string, unknown>>(
    path.join(repoRoot, "evals/end_to_end_agent_release_cases.json"),
  );
  const recordingPayload = readJson<Record<string, unknown>>(
    path.join(repoRoot, "evals/recorded_llm/end_to_end_agent_release.json"),
  );
  assertSafeFixture(profilePayload);
  assertSafeFixture(casePayload);
  assertSafeFixture(recordingPayload);
  if (profilePayload.schema !== "sap-nexus.agent-release-profiles.v1") {
    throw new Error("Unsupported release profile fixture schema");
  }
  if (casePayload.schema !== "sap-nexus.agent-release-cases.v1") {
    throw new Error("Unsupported release case fixture schema");
  }
  if (recordingPayload.schema !== "sap-nexus.recorded-llm-fixtures.v1") {
    throw new Error("Unsupported recorded LLM fixture schema");
  }

  const cases = requireArray(casePayload.cases, "release cases") as ReleaseCaseFixture[];
  const recordings = requireArray(recordingPayload.recordings, "recordings") as RecordedLlmFixture[];
  validateProfiles(profilePayload.profiles);
  validateRecordings(recordings);
  validateCases(cases, recordings);
  return {
    profileVersion: requireText(profilePayload.version, "profile version"),
    scenarioClock: requireTimestamp(profilePayload.scenarioClock, "scenario clock"),
    caseVersion: requireText(casePayload.version, "case version"),
    recordingVersion: requireText(recordingPayload.version, "recording version"),
    cases,
    recordings,
  };
}

export async function runOfflineReleaseScenarios(
  options: ScenarioOptions,
): Promise<ReleaseCaseResult[]> {
  const fixtures = loadReleaseFixtures(options.repoRoot);
  const recordings = new Map(fixtures.recordings.map((recording) => [recording.recordingId, recording]));
  const results: ReleaseCaseResult[] = [];
  const targetIndex = options.target ? maturityIndex(options.target) : 2;
  for (const fixture of fixtures.cases.filter((entry) => maturityIndex(entry.level) <= targetIndex)) {
    try {
      switch (fixture.runner) {
        case "fixture-contract":
          results.push(contractResult(fixture));
          break;
        case "recorded-intent":
          results.push(recordingResult(fixture, recordings));
          break;
        case "python-agent-eval":
          results.push(await runPythonAgentEval(fixture, options.repoRoot));
          break;
        case "governed-read-context":
          results.push(await runGovernedReadContextEval(fixture, options.repoRoot));
          break;
        case "composition-e2e":
          results.push(await runCompositionScenario(fixture, options.now, false));
          break;
        case "action-e2e":
          results.push(await runCompositionScenario(fixture, options.now, true));
          break;
      }
    } catch (error) {
      results.push({
        ...baseResult(fixture),
        status: "failed",
        evidenceRefs: [],
        errorType: scenarioErrorType(error),
      });
    }
  }
  return results;
}

async function runGovernedReadContextEval(
  fixture: ReleaseCaseFixture,
  repoRoot: string,
): Promise<ReleaseCaseResult> {
  const fixtureId = fixture.caseId.replace(/^context-/, "");
  const evidence = (await governedContextEvalEvidence(repoRoot)).get(fixtureId);
  if (!evidence) {
    return {
      ...baseResult(fixture),
      status: "missing",
      evidenceRefs: [],
      errorType: "CONTEXT_EVIDENCE_MISSING",
    };
  }
  const metrics = contextMetrics(evidence);
  Object.assign(metrics, await durableContextMetrics(repoRoot, fixtureId, evidence));
  const passed = contextEvidencePasses(evidence, metrics);
  const durableRef = fixtureId === "concurrent-turns" ? ["durable:lease-conflict", "durable:cas-conflict"]
    : fixtureId === "duplicate-turn-id" ? ["durable:duplicate-turn"]
    : fixtureId === "registry-drift" ? ["durable:stale-continuation"]
    : fixtureId === "read-write-authority-isolation" ? ["durable:write-isolation"]
    : [];
  return {
    ...baseResult(fixture),
    status: passed ? "passed" : "failed",
    evidenceRefs: passed ? [
      `run:${fixture.caseId}`,
      "eval:evals/matcher_cases.yaml",
      ...durableRef,
    ] : [],
    metrics,
    ...(passed ? {} : { errorType: "GOVERNED_READ_CONTEXT_EVIDENCE_FAILED" }),
  };
}

function durableContextMetrics(
  repoRoot: string,
  fixtureId: string,
  evidence: ContextCaseEvidence,
): Promise<Partial<ReleaseMetricCounts>> {
  let pending = durableContextEvalCache.get(repoRoot);
  if (!pending) {
    pending = governedContextEvalEvidence(repoRoot).then(runDurableContextProtocols);
    durableContextEvalCache.set(repoRoot, pending);
  }
  return pending.then((results) => results.get(fixtureId) ?? {});
}

async function runDurableContextProtocols(
  evidence: Map<string, ContextCaseEvidence>,
): Promise<Map<string, Partial<ReleaseMetricCounts>>> {
  const results = new Map<string, Partial<ReleaseMetricCounts>>();
  results.set("duplicate-turn-id", await observeDuplicateTurn(requireProductionTurn(evidence, "direct-plant-switch")));
  results.set("concurrent-turns", await observeConflicts(requireProductionTurn(evidence, "direct-plant-switch")));
  results.set("registry-drift", await observeRejectedContinuation(requireProductionTurn(evidence, "registry-drift")));
  results.set("read-write-authority-isolation", await observeRejectedContinuation(requireProductionTurn(evidence, "read-write-authority-isolation")));
  return results;
}

async function observeDuplicateTurn(turn: ContextTurnEvidence): Promise<Partial<ReleaseMetricCounts>> {
  return withRuntimeProtocol(async (store, runs) => {
    let continuations = 0;
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "continue-read") continuations += 1;
      if (input.mode === "resolve-read" || input.mode === "continue-read") return replayProductionTurn(turn, input);
      throw new Error(`unexpected runtime mode ${input.mode}`);
    });
    const first = await createAgentRun({
      query: "查库存", conversationId: "context-duplicate", turnId: turn.turnId,
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRuntimeTerminal(runs, first.runId);
    const retried = await createAgentRun({
      query: "查库存", conversationId: "context-duplicate", turnId: turn.turnId,
      principal: PLACEHOLDER_PRINCIPAL,
    });
    const session = await store.load("context-duplicate", PLACEHOLDER_PRINCIPAL.principalId);
    return {
      duplicateTurnChecks: 1,
      duplicateTurnGatewayCalls: retried.runId === first.runId && continuations === 1 ? 0 : 1,
      stateOverwritesAfterConflict: session?.lastAppliedTurnId === turn.turnId ? 0 : 1,
    };
  });
}

async function observeConflicts(turn: ContextTurnEvidence): Promise<Partial<ReleaseMetricCounts>> {
  return withRuntimeProtocol(async (store) => {
    const held = await store.claim("context-concurrent", "other-worker", 60_000);
    let busy = false;
    try {
      await createAgentRun({
        query: "查库存", conversationId: "context-concurrent", turnId: turn.turnId,
        principal: PLACEHOLDER_PRINCIPAL,
      });
    } catch (error) {
      busy = error instanceof Error && "code" in error
        && (error as { code?: string }).code === "CONVERSATION_BUSY";
    }
    const session = await store.load("context-concurrent", PLACEHOLDER_PRINCIPAL.principalId);
    if (held.status === "claimed" || held.status === "force-claimed") {
      await store.release("context-concurrent", "other-worker", held.fenceToken);
    }
    return {
      casLeaseConflictChecks: 1,
      stateOverwritesAfterConflict: busy && session === null ? 0 : 1,
    };
  }).then(async (lease) => {
    const cas = await withRuntimeProtocol(async (store, runs) => {
      const realCas = store.compareAndSwap.bind(store);
      let advanced = false;
      store.compareAndSwap = async (...args) => {
        if (!advanced) {
          advanced = true;
          const [conversationId, expectedVersion, next, fence] = args;
          await realCas(conversationId, expectedVersion, {
            ...next, lastAppliedTurnId: "cas-winner", lastRunId: "cas-winner",
          }, fence);
        }
        return realCas(...args);
      };
      setReadAgentRunnerForTests(async (input) => replayProductionTurn(turn, input));
      const started = await createAgentRun({
        query: "查库存", conversationId: "context-cas", turnId: turn.turnId,
        principal: PLACEHOLDER_PRINCIPAL,
      });
      const events = await waitForRuntimeTerminal(runs, started.runId);
      const session = await store.load("context-cas", PLACEHOLDER_PRINCIPAL.principalId);
      const lost = events.at(-1)?.type === "run_failed";
      return {
        casLeaseConflictChecks: 1,
        stateOverwritesAfterConflict: lost && session?.lastAppliedTurnId === "cas-winner" ? 0 : 1,
      };
    });
    return {
      casLeaseConflictChecks: (lease.casLeaseConflictChecks ?? 0) + (cas.casLeaseConflictChecks ?? 0),
      stateOverwritesAfterConflict: (lease.stateOverwritesAfterConflict ?? 0) + (cas.stateOverwritesAfterConflict ?? 0),
    };
  });
}

async function observeRejectedContinuation(turn: ContextTurnEvidence): Promise<Partial<ReleaseMetricCounts>> {
  return withRuntimeProtocol(async (_store, runs) => {
    let continuations = 0;
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "resolve-read" || input.mode === "continue-read") {
        if (input.mode === "continue-read") continuations += 1;
        return replayProductionTurn(turn, input);
      }
      throw new Error(`unexpected production replay ${input.mode}`);
    });
    const started = await createAgentRun({
      query: "继续刚才查询", conversationId: `context-${turn.turnId}`,
      turnId: turn.turnId, principal: PLACEHOLDER_PRINCIPAL,
    });
    const events = await waitForRuntimeTerminal(runs, started.runId);
    const rejected = events.at(-1)?.type === "run_failed" && continuations === 0;
    return turn.callPlan
      ? {
          staleFrameChecks: 1,
          staleFrameExecutions: turn.executeDelta === 0
            && turn.continuation?.errorType !== null ? 0 : 1,
        }
      : {
          readWriteIsolationChecks: 1,
          readContextWriteAuthorityCreations: continuations === 0
            && !turn.writeAuthority.approvalRecord
            && !turn.writeAuthority.selectionBinding ? 0 : 1,
        };
  });
}

async function withRuntimeProtocol<T>(
  operation: (store: JsonlConversationStore, runs: JsonlRunStore) => Promise<T>,
): Promise<T> {
  const directory = runtimeProtocolDirectory ??= createRuntimeProtocolDirectory();
  const runs = new JsonlRunStore(directory, "release-gate-context");
  const store = new JsonlConversationStore(directory);
  await runs.clearAll();
  await store.clearAll();
  setDurableStoresForTests(runs, store);
  try {
    return await operation(store, runs);
  } finally {
    setReadAgentRunnerForTests(null);
    // Keep the injected global stores valid but empty for later test work.
    await runs.clearAll();
    await store.clearAll();
  }
}

function createRuntimeProtocolDirectory(): string {
  const directory = mkdtempSync(path.join(tmpdir(), "sap-nexus-context-protocol-"));
  process.once("exit", () => rmSync(directory, { recursive: true, force: true }));
  return directory;
}

async function waitForRuntimeTerminal(runs: JsonlRunStore, runId: string) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const events = (await runs.load(runId))?.events ?? [];
    if (events.at(-1)?.type === "run_completed" || events.at(-1)?.type === "run_failed") return events;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`runtime protocol run ${runId} did not settle`);
}

function requireProductionTurn(
  evidence: Map<string, ContextCaseEvidence>, caseId: string,
): ContextTurnEvidence {
  const caseEvidence = evidence.get(caseId);
  const turn = caseEvidence?.turns.find((entry) => entry.workbenchOutcome !== null);
  if (!caseEvidence || caseEvidence.status !== "passed" || !turn) {
    throw new Error(`missing production context evidence for ${caseId}`);
  }
  return turn;
}

function replayProductionTurn(turn: ContextTurnEvidence, input: { mode: string; turnId?: string }): WorkbenchOutcome {
  if (input.mode === "resolve-read") {
    if (input.turnId !== turn.turnId) throw new Error("production turn binding mismatch");
    return turn.workbenchOutcome;
  }
  if (input.mode === "continue-read" && turn.continuation) {
    return turn.continuation.workbenchOutcome;
  }
  throw new Error(`missing immutable production replay for ${input.mode}`);
}

function governedContextEvalEvidence(repoRoot: string): Promise<Map<string, ContextCaseEvidence>> {
  const cached = governedContextEvalCache.get(repoRoot);
  if (cached) return cached;
  const pending = runProcess(
    path.join(repoRoot, ".venv/bin/python"),
    ["-m", "sap_nexus_agent.eval", "evals/matcher_cases.yaml", "--context-evidence"],
    repoRoot,
  ).then((result) => {
    if (result.code !== 0) return new Map();
    const payload = JSON.parse(result.stdout) as { cases?: ContextCaseEvidence[] };
    return new Map((payload.cases ?? []).map((entry) => [entry.caseId, entry]));
  });
  governedContextEvalCache.set(repoRoot, pending);
  return pending;
}

function contractResult(fixture: ReleaseCaseFixture): ReleaseCaseResult {
  return {
    ...baseResult(fixture),
    status: "passed",
    evidenceRefs: [
      "fixture:evals/end_to_end_agent_release_cases.json",
      `fixture-case:${fixture.caseId}`,
    ],
  };
}

function recordingResult(
  fixture: ReleaseCaseFixture,
  recordings: Map<string, RecordedLlmFixture>,
): ReleaseCaseResult {
  const recording = fixture.recordingId ? recordings.get(fixture.recordingId) : undefined;
  const passed = Boolean(recording)
    && recording!.normalizedResponse.capabilityIds.every((capabilityId) =>
      VISIBLE_CAPABILITIES.has(capabilityId));
  return {
    ...baseResult(fixture),
    status: passed ? "passed" : "failed",
    evidenceRefs: passed ? [
      "fixture:evals/recorded_llm/end_to_end_agent_release.json",
      `recording:${recording!.recordingId}@${recording!.version}`,
    ] : [],
    ...(passed ? {} : { errorType: "RECORDED_FIXTURE_INVALID" }),
  };
}

async function runPythonAgentEval(
  fixture: ReleaseCaseFixture,
  repoRoot: string,
): Promise<ReleaseCaseResult> {
  const result = await runProcess(
    path.join(repoRoot, ".venv/bin/python"),
    ["-m", "sap_nexus_agent.eval", "evals/eval_harness_seed_cases.json"],
    repoRoot,
  );
  const match = /Eval passed:\s*(\d+)\/(\d+)/.exec(result.stdout);
  const passed = result.code === 0 && match !== null && match[1] === match[2];
  const checked = match ? Number(match[2]) : 0;
  return {
    ...baseResult(fixture),
    status: passed ? "passed" : "failed",
    evidenceRefs: passed ? [
      `run:${fixture.caseId}`,
      "eval:evals/eval_harness_seed_cases.json",
    ] : [],
    metrics: { ...emptyMetrics(), visibilityChecks: checked },
    ...(passed ? {} : { errorType: "AGENT_EVAL_FAILED" }),
  };
}

async function runCompositionScenario(
  fixture: ReleaseCaseFixture,
  now: string,
  includeAction: boolean,
): Promise<ReleaseCaseResult> {
  const directory = mkdtempSync(path.join(tmpdir(), "sap-nexus-release-gate-"));
  try {
    const runId = `run-${fixture.caseId}`;
    const traceId = `trace-${fixture.caseId}`;
    const store = new JsonlRunStore(directory, `worker-${fixture.caseId}`);
    await store.save(runId, seedRun(runId, now));
    const readGateway = configuredReadGateway(now);
    const coordinator = new CompositionCoordinator({
      store,
      gateway: readGateway,
      workerId: `worker-${fixture.caseId}`,
      now: () => now,
    });
    const outcome = await coordinator.execute({
      runId,
      traceId,
      principal: PLACEHOLDER_PRINCIPAL,
      handoff: {
        graph: includeAction ? readToWriteGraph() : dualReadGraph(),
        snapshotId: SNAPSHOT_ID,
      },
      locale: "en",
    });
    return includeAction
      ? await runActionContinuation(fixture, store, outcome, now, runId, traceId, readGateway)
      : await verifyReadComposition(fixture, store, outcome, runId, traceId, readGateway);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

async function verifyReadComposition(
  fixture: ReleaseCaseFixture,
  store: JsonlRunStore,
  outcome: Awaited<ReturnType<CompositionCoordinator["execute"]>>,
  runId: string,
  traceId: string,
  gateway: FakeGateway,
): Promise<ReleaseCaseResult> {
  const executeCount = gateway.executeCalls.length;
  const firstReplay = await store.load(runId);
  const secondReplay = await store.load(runId);
  const snapshot = secondReplay?.events.reduce(applyRunEvent, createInitialSnapshot(runId));
  const checks = {
    projectionComplete: outcome.projection.completeness === "complete",
    noAction: outcome.actionGovernanceInput === undefined,
    claimsGrounded: outcome.narrative.claims.every((claim) => claim.evidenceRefs.length > 0),
    lineageComplete: completeLineage(outcome.projection.lineage),
    replayPresent: firstReplay !== null,
    replayStable: JSON.stringify(firstReplay) === JSON.stringify(secondReplay),
    sequenceComplete: firstReplay !== null && sequential(firstReplay.events.map((event) => event.sequence)),
    workbenchCompleted: snapshot?.state === "completed",
    readsExecutedOnce: executeCount === 2 && gateway.executeCalls.length === executeCount,
  };
  const failedChecks = Object.entries(checks).filter(([, passed]) => !passed).map(([name]) => name);
  return compositionResult(fixture, outcome, failedChecks.length === 0, [
    `run:${runId}`,
    `trace:${traceId}`,
    `projection:${outcome.projection.outputHash}`,
  ], failedChecks.length > 0 ? `COMPOSITION_EVIDENCE_FAILED_${failedChecks.join("_")}` : undefined);
}

async function runActionContinuation(
  fixture: ReleaseCaseFixture,
  store: JsonlRunStore,
  outcome: Awaited<ReturnType<CompositionCoordinator["execute"]>>,
  now: string,
  runId: string,
  traceId: string,
  readGateway: FakeGateway,
): Promise<ReleaseCaseResult> {
  const actionGateway = new OfflineActionGateway();
  const continuation = new PlanActionContinuation(store, actionGateway, `action-${fixture.caseId}`);
  if (!outcome.actionGovernanceInput) {
    throw new Error("Action scenario did not produce governance input");
  }
  const pending = await continuation.prepare(outcome.actionGovernanceInput);
  const unapprovedExecuteCount = actionGateway.executeCalls;
  await continuation.recordDecision(
    runId,
    pending.approvalId,
    "approve",
    PLACEHOLDER_PRINCIPAL,
    new Date(Date.parse(now) + 60_000).toISOString(),
  );
  const executedAt = new Date(Date.parse(now) + 120_000).toISOString();
  const first = await continuation.executeDurable(
    runId,
    pending.approvalId,
    PLACEHOLDER_PRINCIPAL,
    executedAt,
  );
  const repeated = await continuation.executeDurable(
    runId,
    pending.approvalId,
    PLACEHOLDER_PRINCIPAL,
    executedAt,
  );
  const writeCount = actionGateway.executeCalls;
  const readCount = readGateway.executeCalls.length;
  const firstReplay = await store.load(runId);
  const secondReplay = await store.load(runId);
  const snapshot = secondReplay?.events.reduce(applyRunEvent, createInitialSnapshot(runId));
  const passed = unapprovedExecuteCount === 0
    && first.status === "executed"
    && repeated.status === "executed"
    && JSON.stringify(first) === JSON.stringify(repeated)
    && writeCount === 1
    && actionGateway.executeCalls === writeCount
    && readCount === 2
    && readGateway.executeCalls.length === readCount
    && firstReplay !== null
    && JSON.stringify(firstReplay) === JSON.stringify(secondReplay)
    && sequential(firstReplay.events.map((event) => event.sequence))
    && snapshot?.state === "completed";
  const base = compositionResult(fixture, outcome, passed, [
    `run:${runId}`,
    `trace:${traceId}`,
    `approval:${pending.approvalId}`,
    `action:${actionGateway.traceId}`,
  ]);
  return {
    ...base,
    metrics: {
      ...base.metrics,
      writeApprovalChecks: 2,
      writeApprovalBypasses: unapprovedExecuteCount,
    },
  };
}

function compositionResult(
  fixture: ReleaseCaseFixture,
  outcome: Awaited<ReturnType<CompositionCoordinator["execute"]>>,
  passed: boolean,
  evidenceRefs: string[],
  failureType?: string,
): ReleaseCaseResult {
  const linked = outcome.projection.lineage.filter((entry) => (
    entry.factId.length > 0 && Object.keys(entry.evidence).length > 0
  )).length;
  return {
    ...baseResult(fixture),
    status: passed ? "passed" : "failed",
    evidenceRefs: passed ? evidenceRefs : [],
    metrics: {
      ...emptyMetrics(),
      narrativeClaims: outcome.narrative.claims.length,
      unsupportedNarrativeClaims: outcome.narrative.claims.filter((claim) =>
        claim.evidenceRefs.length === 0).length,
      lineageRequired: outcome.projection.lineage.length,
      lineageLinked: linked,
    },
    ...(passed ? {} : { errorType: failureType ?? "COMPOSITION_EVIDENCE_FAILED" }),
  };
}

function baseResult(fixture: ReleaseCaseFixture): Omit<ReleaseCaseResult, "status" | "evidenceRefs"> {
  return {
    caseId: fixture.caseId,
    level: fixture.level,
    stage: fixture.stage,
    fixtureKind: fixture.fixtureKind,
    metrics: emptyMetrics(),
  };
}

function emptyMetrics(): ReleaseMetricCounts {
  return {
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
  };
}

function contextMetrics(evidence: ContextCaseEvidence): ReleaseMetricCounts {
  const turns = evidence.turns;
  const contextualConflicts = turns.filter(hasObservedContextConflict);
  const nonReady = turns.filter((turn) => turn.frame.status !== "READY");
  const callPlanChecks = turns.flatMap(observedCallPlanSlotChecks);
  const deterministicPasses = turns.filter((turn) => (
    (turn.decision !== "SELECT" || (turn.frame.status === "READY" && turn.callPlan !== null))
    && !(turn.frame.status !== "READY" && (turn.validateDelta > 0 || turn.executeDelta > 0))
    && !turn.writeAuthority.approvalRecord
    && !turn.writeAuthority.selectionBinding
  ));
  const recoveryTurns = turns.filter((turn) => {
    const active = turn.stateBefore?.activeFrame;
    return isRecord(active)
      && (active.status === "COLLECTING" || active.status === "CONFLICTED")
      && turn.frame.status === "READY";
  });
  const successfulRecoveries = recoveryTurns.filter((turn) => (
    turn.decision === "SELECT" && turn.callPlan !== null && turn.executeDelta === 1
  ));
  return {
    ...emptyMetrics(),
    // Context-specific completeness only applies to observed resolver issues.
    contextConflictCases: contextualConflicts.length,
    falseSelects: turns.filter((turn) => (
      turn.decision === "SELECT" && (turn.frame.status !== "READY" || turn.callPlan === null)
    )).length,
    nonReadyFrames: nonReady.length,
    nonReadyGatewayCalls: nonReady.reduce(
      (total, turn) => total + turn.validateDelta + turn.executeDelta,
      0,
    ),
    callPlanSlotChecks: callPlanChecks.length,
    wrongCallPlanSlotRoles: callPlanChecks.filter((check) => !check.valid).length,
    // Only the dedicated durable probe proves the READ-to-WRITE boundary.
    readWriteIsolationChecks: 0,
    readContextWriteAuthorityCreations: 0,
    deterministicCoreChecks: turns.length,
    deterministicCorePassed: deterministicPasses.length,
    successfulRecoveryChecks: recoveryTurns.length,
    successfulRecoveries: successfulRecoveries.length,
  };
}

function hasObservedContextConflict(turn: ContextTurnEvidence): boolean {
  const report = turn.workbenchOutcome.resolutionReport;
  if (!isRecord(report) || !Array.isArray(report.issues)) return false;
  return report.issues.some((issue) => typeof issue === "string" && (
    issue.startsWith("missing_required:")
    || issue.startsWith("invalid_semantic_value:")
    || issue.startsWith("context_")
  ));
}

function observedCallPlanSlotChecks(turn: ContextTurnEvidence): Array<{ valid: boolean }> {
  if (!turn.callPlan) return [];
  return Object.entries(turn.callPlan.parameters)
    .filter(([parameter]) => parameter in turn.slots)
    .map(([parameter, value]) => {
      const slot = turn.slots[parameter];
      const role = turn.callPlan?.slotRoles[parameter];
      return {
        valid: slot.value === value
          && slot.state === "RESOLVED"
          && role === slot.role
          && role !== "MODEL_CANDIDATE"
          && role !== "INHERITED_LEGACY",
      };
    });
}

function contextEvidencePasses(
  evidence: ContextCaseEvidence,
  metrics: ReleaseMetricCounts,
): boolean {
  // Kept in sync with evaluator.ts's `requiredContextEvidenceError`: each
  // entry is a fixture whose own evidence is the (only) legitimate source of
  // a non-zero denominator for the named aggregate metric. Checking the
  // exact expected count here — not just that the numerator stayed 0 —
  // catches a regression where the denominator itself silently drops to 0.
  const requiredEvidence: Record<string, ReadonlyArray<readonly [keyof ReleaseMetricCounts, number]>> = {
    "duplicate-turn-id": [["duplicateTurnChecks", 1]],
    "concurrent-turns": [["casLeaseConflictChecks", 2]],
    "registry-drift": [["staleFrameChecks", 1]],
    "read-write-authority-isolation": [["readWriteIsolationChecks", 1]],
    "clear-then-ambiguous-reference": [
      ["contextConflictCases", 2],
      ["callPlanSlotChecks", 2],
    ],
    "llm-unavailable": [["nonReadyFrames", 1]],
    "malformed-json": [["nonReadyFrames", 1]],
    "capability-switch": [["callPlanSlotChecks", 3]],
  };
  const durableRequired = (requiredEvidence[evidence.caseId] ?? [])
    .every(([metric, expected]) => metrics[metric] === expected);
  return evidence.status === "passed"
    && evidence.failureRefs.length === 0
    && durableRequired
    && evidence.fixtureVersion === "governed-read-context-v1"
    && evidence.registrySnapshotId.length > 0
    && evidence.turns.length > 0
    && metrics.falseSelects === 0
    && metrics.nonReadyGatewayCalls === 0
    && metrics.wrongCallPlanSlotRoles === 0
    && metrics.readContextWriteAuthorityCreations === 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function dualReadGraph(): PlanGraphV2 {
  const bindings = [
    { parameterName: "material", source: { kind: "literal" as const, semanticType: "MaterialCode", value: "MAT-1" } },
    { parameterName: "plant", source: { kind: "literal" as const, semanticType: "PlantCode", value: "P1" } },
  ];
  return {
    planGraphVersion: 2,
    planId: "plan-release-gate",
    goalId: "goal-release-gate",
    executionMode: "advisory",
    snapshotId: SNAPSHOT_ID,
    nodes: [
      {
        nodeId: "node.inventory",
        capabilityId: "MM.Inventory.GetAvailability",
        parameterBindings: bindings,
        producesFactTypes: ["InventoryAvailability"],
        governance: { requiresApproval: false },
      },
      {
        nodeId: "node.purchase-orders",
        capabilityId: "MM.PurchaseOrder.GetList",
        parameterBindings: bindings,
        producesFactTypes: ["PurchaseOrder"],
        governance: { requiresApproval: false },
      },
    ],
    edges: [],
    topologicalOrder: ["node.inventory", "node.purchase-orders"],
    goalOutputs: [],
    readPartition: ["node.inventory", "node.purchase-orders"],
    actionPartition: [],
    projectionRef: [],
    ruleSetRefs: [],
  };
}

function readToWriteGraph(): PlanGraphV2 {
  const graph = dualReadGraph();
  return {
    ...graph,
    executionMode: "READ_THEN_SINGLE_ACTION",
    nodes: [...graph.nodes, {
      nodeId: "node.action",
      capabilityId: "MM.PR.CreateDraft",
      parameterBindings: [
        { parameterName: "quantity", source: { kind: "literal", semanticType: "Quantity", value: "10" } },
        { parameterName: "delivery_date", source: { kind: "literal", semanticType: "Date", value: "2026-08-15" } },
        { parameterName: "purchasing_group", source: { kind: "literal", semanticType: "PurchasingGroup", value: "601" } },
      ],
      producesFactTypes: [],
      governance: { requiresApproval: true },
    }],
    topologicalOrder: [...graph.topologicalOrder, "node.action"],
    actionPartition: ["node.action"],
  };
}

function configuredReadGateway(now: string): FakeGateway {
  const gateway = new FakeGateway();
  gateway.setExecuteResult("MM.Inventory.GetAvailability", {
    success: true,
    traceId: "gateway-release-inventory",
    data: {
      availableQuantity: 7,
      unit: "EA",
      material: "MAT-1",
      plant: "P1",
      dataAsOf: now,
    },
  });
  gateway.setExecuteResult("MM.PurchaseOrder.GetList", {
    success: true,
    traceId: "gateway-release-purchase-orders",
    data: {
      purchaseOrders: [{
        purchaseOrder: "4500001",
        purchaseOrderItem: "10",
        orderQuantity: 5,
        purchaseOrderUnit: "EA",
        material: "MAT-1",
        plant: "P1",
      }],
      dataAsOf: now,
    },
  });
  return gateway;
}

function seedRun(runId: string, now: string): AgentRunRecord {
  return {
    runId,
    query: "evaluate governed material supply composition",
    principalId: PLACEHOLDER_PRINCIPAL.principalId,
    events: [{
      runId,
      sequence: 1,
      timestamp: now,
      type: "run_started",
      state: "running",
    }],
  };
}

class OfflineActionGateway implements ActionGateway {
  readonly traceId = "gateway-release-action";
  approveCalls = 0;
  executeCalls = 0;

  async approve(): Promise<void> {
    this.approveCalls += 1;
  }

  async execute(_request: ActionGatewayRequest) {
    this.executeCalls += 1;
    return {
      success: true,
      traceId: this.traceId,
      data: { prNumber: "offline-sandbox-10000001" },
      returnMessages: [{ type: "S", message: "offline sandbox draft created" }],
    };
  }
}

function completeLineage(lineage: Array<{ factId: string; evidence: Record<string, unknown> }>): boolean {
  return lineage.length > 0 && lineage.every((entry) => (
    entry.factId.length > 0 && Object.keys(entry.evidence).length > 0
  ));
}

function sequential(sequences: number[]): boolean {
  return sequences.every((sequence, index) => sequence === index + 1);
}

function maturityIndex(level: MaturityLevel): number {
  return (["L1", "L2", "L3"] as MaturityLevel[]).indexOf(level);
}

function validateProfiles(value: unknown): void {
  const profiles = requireArray(value, "profiles") as Array<Record<string, unknown>>;
  const levels = new Set(profiles.map((profile) => profile.level));
  if (levels.size !== 3 || !["L1", "L2", "L3"].every((level) => levels.has(level))) {
    throw new Error("Release profiles must declare L1, L2 and L3");
  }
}

function validateCases(cases: ReleaseCaseFixture[], recordings: RecordedLlmFixture[]): void {
  const recordingIds = new Set(recordings.map((recording) => recording.recordingId));
  for (const fixture of cases) {
    requireText(fixture.caseId, "caseId");
    requireText(fixture.stage, "stage");
    requireArray(fixture.evidenceRequirements, `${fixture.caseId} evidence requirements`);
    requireArray(fixture.hardGateImpact, `${fixture.caseId} hard gate impact`);
    requireArray(fixture.riskTags, `${fixture.caseId} risk tags`);
    if (!fixture.evidenceRequirements.length || !fixture.riskTags.length) {
      throw new Error(`Release case ${fixture.caseId} is missing evidence or risk declarations`);
    }
    if (fixture.fixtureKind === "recorded-llm"
        && (!fixture.recordingId || !recordingIds.has(fixture.recordingId))) {
      throw new Error(`Release case ${fixture.caseId} references an unknown recording`);
    }
  }
}

function validateRecordings(recordings: RecordedLlmFixture[]): void {
  for (const recording of recordings) {
    requireText(recording.recordingId, "recordingId");
    requireText(recording.provider, "recording provider");
    requireText(recording.model, "recording model");
    requireText(recording.promptVersion, "prompt version");
    requireText(recording.responseSchema, "response schema");
    requireText(recording.recordedAt, "recordedAt");
    requireText(recording.version, "recording version");
    if (recording.redacted !== true) {
      throw new Error(`Recording ${recording.recordingId} must declare redaction`);
    }
    if (!recording.normalizedResponse
        || !Array.isArray(recording.normalizedResponse.capabilityIds)
        || recording.normalizedResponse.capabilityIds.some((id) => !VISIBLE_CAPABILITIES.has(id))) {
      throw new Error(`Recording ${recording.recordingId} is not closed-set`);
    }
  }
}

function assertSafeFixture(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(assertSafeFixture);
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, nested] of Object.entries(value)) {
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) {
      throw new Error(`Forbidden fixture key: ${key}`);
    }
    assertSafeFixture(nested);
  }
}

function readJson<T>(file: string): T {
  return JSON.parse(readFileSync(file, "utf8")) as T;
}

function requireArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

function requireText(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${label} must be non-empty`);
  }
  return value;
}

function requireTimestamp(value: unknown, label: string): string {
  const timestamp = requireText(value, label);
  if (!Number.isFinite(Date.parse(timestamp))) throw new Error(`${label} must be an ISO timestamp`);
  return timestamp;
}

function runProcess(command: string, args: string[], cwd: string): Promise<{
  code: number | null;
  stdout: string;
}> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    child.stdout.on("data", (chunk) => { stdout += String(chunk); });
    child.once("error", reject);
    child.once("close", (code) => resolve({ code, stdout }));
  });
}

function scenarioErrorType(error: unknown): string {
  if (error && typeof error === "object" && "errorType" in error) {
    const errorType = (error as { errorType?: unknown }).errorType;
    if (typeof errorType === "string" && /^[A-Z0-9_]+$/.test(errorType)) return errorType;
  }
  return "OFFLINE_SCENARIO_FAILED";
}
