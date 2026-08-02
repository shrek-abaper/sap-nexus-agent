import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import type { AgentRunEvent, AgentRunState } from "./run-event-schema";
import type {
  AgentRunRecord,
  ApprovalDecision,
  ConversationContext,
  DurableConversationStore,
  DurableRunStore,
  LastContext,
  SessionState,
  Turn,
  WorkbenchOutcome
} from "./durable/types";
import { JsonlConversationStore } from "./durable/jsonl-conversation-store";
import { JsonlRunStore } from "./durable/jsonl-run-store";
import { canonicalJson, sha256Hex } from "./durable/canonical-json";
import { idempotencyKey } from "./durable/idempotency";
import type { ContinuationType } from "./durable/types";

export type { ApprovalDecision } from "./durable/types";

import { redactArtifact } from "./redaction";
import type { JsonValue } from "../shared/types/artifacts";

type CreateAgentRunInput = {
  query: string;
  rfcName?: string;
  conversationId?: string;
};

type ApprovalContinuation = {
  type?: "approval";
  decision: ApprovalDecision;
  callPlan: Record<string, unknown>;
  validationResult: Record<string, unknown>;
  approvalRecord: Record<string, unknown>;
};

type BatchContinuation = {
  type: "batch";
  callPlan: Record<string, unknown>;
  combinations: Record<string, string>[];
};

type AgentRunnerInput = {
  query: string;
  gatewayUrl: string;
  intentMode: string;
  continuation?: ApprovalContinuation | BatchContinuation;
  context?: ConversationContext;
};

type AgentRunner = (input: AgentRunnerInput) => Promise<WorkbenchOutcome>;

const workbenchDataDir = process.env.WORKBENCH_DATA_DIR ?? path.join(process.cwd(), ".workbench-data");
const durableDataDir = path.join(workbenchDataDir, "durable");
const workerId = process.env.WORKER_ID ?? `worker-${process.pid}`;

let runStore: DurableRunStore = new JsonlRunStore(durableDataDir, workerId);
let conversationStore: DurableConversationStore = new JsonlConversationStore(durableDataDir);
let runnerForTests: AgentRunner | null = null;

export function setAgentRunnerForTests(runner: AgentRunner | null) {
  runnerForTests = runner;
}

export function setDurableStoresForTests(run: DurableRunStore, conv: DurableConversationStore) {
  runStore = run;
  conversationStore = conv;
}

export function resetAgentRunsForTests() {
  void runStore.clearAll();
}

export function resetAgentSessionsForTests() {
  void conversationStore.clearAll();
}

async function getSession(conversationId: string): Promise<SessionState> {
  const existing = await conversationStore.load(conversationId);
  if (existing) return existing;
  const session: SessionState = { lastContext: null, lastRunId: null, history: [] };
  await conversationStore.save(conversationId, session);
  return session;
}

function buildContext(session: SessionState): ConversationContext | undefined {
  if (!session.lastContext) return undefined;
  // Align with Python llm_intent.py `context.history[-6:]`: 近 3 轮 =
  // user+assistant = 6 条 Turn (Concern 3).
  const recent = session.history.slice(-6);
  return {
    lastContext: session.lastContext,
    history: recent.length > 0 ? recent : null
  };
}

export async function createAgentRun(input: CreateAgentRunInput): Promise<{ runId: string }> {
  if (input.rfcName) {
    throw new Error("Raw RFC execution is not allowed");
  }

  // Q2: reject new queries on a conversation that still has a pending write approval.
  if (input.conversationId) {
    const session = await getSession(input.conversationId);
    const lastRunId = session.lastRunId;
    if (lastRunId) {
      const lastRun = await runStore.load(lastRunId);
      if (lastRun?.pendingOutcome && !lastRun.decision) {
        throw new Error("当前对话有待审批的写操作，请先处理审批后再发起新查询。");
      }
    }
  }

  const runId = `run-${crypto.randomUUID()}`;
  const timestamp = new Date().toISOString();
  const query = input.query;
  const record: AgentRunRecord = {
    runId,
    query,
    events: [{ runId, sequence: 1, timestamp, type: "run_started", state: "running" }]
  };
  await runStore.save(runId, record);
  await runStore.claim(runId, workerId, 60_000);

  try {
    const runner = runnerForTests ?? runLocalPythonAgent;
    const context = input.conversationId ? buildContext(await getSession(input.conversationId)) : undefined;
    const outcome = await runner({ query, gatewayUrl: gatewayUrl(), intentMode: intentMode(), context });
    const events = buildEventsFromOutcome(runId, query, outcome, timestamp);
    for (const event of events.slice(1)) {
      await runStore.appendEvent(runId, event);
    }
    record.events = events;
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      record.pendingOutcome = outcome;
      await runStore.appendPendingOutcome(runId, outcome);
      await runStore.release(runId, workerId);
    }

    if (input.conversationId) {
      const session = await getSession(input.conversationId);
      session.lastRunId = runId;
      session.history.push({ role: "user", content: query });
      if (outcome.responseText) {
        session.history.push({ role: "assistant", content: outcome.responseText });
      }
      session.lastContext = outcome.lastContext ?? null;
      await conversationStore.save(input.conversationId, session);
    }
    // success/completed terminal state: run no longer needs the lease
    await runStore.release(runId, workerId);
  } catch (error) {
    const failEvents = buildRuntimeFailureEvents(runId, timestamp, error);
    for (const event of failEvents.slice(1)) {
      await runStore.appendEvent(runId, event);
    }
    record.events = failEvents;
    await runStore.release(runId, workerId);
  }

  return { runId };
}

export async function getAgentRunEvents(runId: string): Promise<AgentRunEvent[]> {
  const run = await runStore.load(runId);
  return run ? run.events : [];
}

export async function decideAgentRunApproval(runId: string, decision: ApprovalDecision): Promise<void> {
  const record = await runStore.load(runId);
  if (!record) {
    throw new Error("Agent run not found");
  }

  // idempotency: a retried continuation returns the already-recorded result
  // without re-executing. Checked before the pendingOutcome/decision guards so
  // a duplicate request is a no-op rather than an "already decided" error.
  const continuationType: ContinuationType = decision === "approve" ? "approval_approve" : "approval_reject";
  const approvalRecordForIdem = objectOrNull(record.pendingOutcome?.approvalRecord);
  const approvalRecordId =
    textValue(approvalRecordForIdem?.id) ?? sha256Hex(canonicalJson(approvalRecordForIdem)).slice(0, 16);
  const idemKey = idempotencyKey(runId, continuationType, { decision, approvalRecordId });
  if (await runStore.lookupExecuted(idemKey)) {
    return;
  }

  if (!record.pendingOutcome) {
    throw new Error("Agent run is not awaiting approval");
  }
  if (record.decision) {
    throw new Error("Agent run approval was already decided");
  }

  const callPlan = objectOrNull(record.pendingOutcome.callPlan);
  const validationResult = objectOrNull(record.pendingOutcome.validationResult);
  const approvalRecord = objectOrNull(record.pendingOutcome.approvalRecord);
  if (!callPlan || !validationResult || !approvalRecord) {
    throw new Error("Agent run approval context is incomplete");
  }

  const lease = await runStore.claim(runId, workerId, 60_000);
  if (lease.status === "rejected") {
    throw new Error(`Agent run is held by another worker (${lease.holder}); takeover rejected (fail-closed).`);
  }
  // lease.status === "claimed" | "force-claimed" -> proceed (audited)
  await runStore.appendDecision(runId, decision);
  const runner = runnerForTests ?? runLocalPythonAgent;
  try {
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { decision, callPlan, validationResult, approvalRecord }
    });
    const newEvents = buildApprovalEvents(record, outcome, new Date().toISOString());
    for (const event of newEvents) {
      await runStore.appendEvent(runId, event);
    }
    await runStore.markExecuted(idemKey, outcome);
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      await runStore.release(runId, workerId);
    }
  } catch (error) {
    const failEvents = buildRuntimeFailureEventsTail(record.runId, record.events.length, new Date().toISOString(), error);
    for (const event of failEvents) {
      await runStore.appendEvent(runId, event);
    }
    await runStore.release(runId, workerId);
  }
}

export async function confirmAgentRunBatch(runId: string): Promise<void> {
  const record = await runStore.load(runId);
  if (!record) {
    throw new Error("Agent run not found");
  }

  // idempotency: a retried batch confirmation returns the already-recorded
  // result without re-executing. Checked before the guards so a duplicate
  // request is a no-op rather than an "already decided" error.
  const idemKey = idempotencyKey(runId, "batch_confirm", {
    combinations: record.pendingOutcome?.combinations ?? []
  });
  if (await runStore.lookupExecuted(idemKey)) {
    return;
  }

  if (!record.pendingOutcome) {
    throw new Error("Agent run is not awaiting batch confirmation");
  }
  if (record.decision) {
    throw new Error("Agent run was already decided");
  }

  const callPlan = objectOrNull(record.pendingOutcome.callPlan);
  const combinations = record.pendingOutcome.combinations ?? null;
  if (!callPlan || !combinations) {
    throw new Error("Agent run batch context is incomplete");
  }

  const lease = await runStore.claim(runId, workerId, 60_000);
  if (lease.status === "rejected") {
    throw new Error(`Agent run is held by another worker (${lease.holder}); takeover rejected (fail-closed).`);
  }
  // lease.status === "claimed" | "force-claimed" -> proceed (audited)
  await runStore.appendDecision(runId, "approve");
  const runner = runnerForTests ?? runLocalPythonAgent;
  try {
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { type: "batch", callPlan, combinations }
    });
    const newEvents = buildBatchEvents(record, outcome, new Date().toISOString());
    for (const event of newEvents) {
      await runStore.appendEvent(runId, event);
    }
    await runStore.markExecuted(idemKey, outcome);
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      await runStore.release(runId, workerId);
    }
  } catch (error) {
    const failEvents = buildRuntimeFailureEventsTail(record.runId, record.events.length, new Date().toISOString(), error);
    for (const event of failEvents) {
      await runStore.appendEvent(runId, event);
    }
    await runStore.release(runId, workerId);
  }
}

export function getTraceMetadata(traceId: string) {
  return {
    traceId,
    status: "available",
    redacted: true
  };
}

function buildEventsFromOutcome(
  runId: string,
  query: string,
  outcome: WorkbenchOutcome,
  timestamp: string
): AgentRunEvent[] {
  const events: AgentRunEvent[] = [{ runId, sequence: 1, timestamp, type: "run_started", state: "running" }];
  const callPlan = objectOrNull(outcome.callPlan);
  const validation = objectOrNull(outcome.validationResult);
  const execution = objectOrNull(outcome.executionResult);
  const fact = objectOrNull(outcome.fact);
  const capabilityId = textValue(callPlan?.capabilityId) ?? textValue(validation?.capabilityId) ?? textValue(execution?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId) ?? textValue(fact?.agentTraceId);
  const gatewayTraceId =
    textValue(outcome.gatewayTraceId) ?? textValue(execution?.traceId) ?? textValue(validation?.traceId);

  push(events, runId, timestamp, {
    type: "intent_parsed",
    state: "intent_parsed",
    capabilityId,
    artifact: redactArtifact({
      label: "IntentParseResult",
      kind: "intent",
      payload: toJsonValue({
        query,
        status: outcome.status,
        parameters: objectOrNull(callPlan?.parameters) ?? {},
        missingParameters: outcome.missingParameters ?? []
      })
    })
  });

  if (!callPlan) {
    pushTerminalOutcome(events, runId, timestamp, outcome, agentTraceId, gatewayTraceId);
    return events;
  }

  push(events, runId, timestamp, {
    type: "capability_selected",
    state: "capability_selected",
    capabilityId,
    artifact: redactArtifact({
      label: "Capability Selection",
      kind: "capability",
      payload: toJsonValue({ capabilityId, kind: callPlan.kind ?? "Function" })
    })
  });
  push(events, runId, timestamp, {
    type: "callplan_created",
    state: "callplan_created",
    capabilityId,
    agentTraceId,
    artifact: redactArtifact({ label: "CallPlan", kind: "callplan", payload: toJsonValue(callPlan) })
  });
  const isAction = callPlan.kind === "Action";
  if (!isAction) {
    push(events, runId, timestamp, {
      type: "approval_state_changed",
      state: "approval_checked",
      hitlState: "approval_not_required"
    });
  }

  if (validation) {
    push(events, runId, timestamp, {
      type: "gateway_validate_started",
      state: "validating",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(validation.traceId) ?? gatewayTraceId
    });
    push(events, runId, timestamp, {
      type: "gateway_validate_completed",
      state: "validating",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(validation.traceId) ?? gatewayTraceId,
      artifact: redactArtifact({ label: "Gateway Validation", kind: "validation", payload: toJsonValue(validation) })
    });
    if (validation.success === false) {
      pushFailure(events, runId, timestamp, "validating", outcome);
      return events;
    }
  }

  if (isAction && outcome.status === "awaiting_approval") {
    const approvalRecord = objectOrNull(outcome.approvalRecord);
    push(events, runId, timestamp, {
      type: "approval_state_changed",
      state: "awaiting_approval",
      hitlState: "approval_required"
    });
    push(events, runId, timestamp, {
      type: "approval_state_changed",
      state: "awaiting_approval",
      hitlState: "awaiting_human_approval",
      artifact: approvalRecord
        ? redactArtifact({
            label: "ApprovalRecord",
            kind: "approval",
            payload: toJsonValue(approvalRecord)
          })
        : undefined
    });
    return events;
  }

  if (outcome.status === "awaiting_batch_confirm") {
    const combinations = outcome.combinations ?? null;
    push(events, runId, timestamp, {
      type: "batch_confirm_requested",
      state: "awaiting_batch_confirm",
      capabilityId,
      agentTraceId,
      artifact: combinations
        ? redactArtifact({
            label: "BatchCombinations",
            kind: "callplan",
            payload: toJsonValue({ combinations, callPlan })
          })
        : undefined
    });
    return events;
  }

  if (execution) {
    push(events, runId, timestamp, {
      type: "gateway_execute_started",
      state: "executing",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(execution.traceId) ?? gatewayTraceId
    });
    push(events, runId, timestamp, {
      type: "gateway_execute_completed",
      state: "executing",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(execution.traceId) ?? gatewayTraceId,
      artifact: redactArtifact({ label: "ExecutionResult", kind: "execution-result", payload: toJsonValue(execution) })
    });
    if (execution.success === false) {
      pushFailure(events, runId, timestamp, "executing", outcome);
      return events;
    }
  }

  if (fact) {
    push(events, runId, timestamp, {
      type: "reasoning_fact_created",
      state: "fact_created",
      capabilityId,
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({ label: "ReasoningFact", kind: "reasoning-fact", payload: toJsonValue(fact) })
    });
  }

  if (outcome.responseText) {
    push(events, runId, timestamp, {
      type: "narrative_created",
      state: "narrated",
      artifact: redactArtifact({
        label: "Chinese Narrative",
        kind: "narrative",
        payload: toJsonValue({ text: outcome.responseText })
      })
    });
  }

  if (agentTraceId || gatewayTraceId) {
    push(events, runId, timestamp, {
      type: "trace_linked",
      state: "trace_linked",
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({
        label: "Trace Metadata",
        kind: "trace",
        payload: toJsonValue({ agentTraceId, gatewayTraceId, status: "linked" })
      })
    });
  }

  if (outcome.status === "success" || outcome.status === "clarification") {
    push(events, runId, timestamp, { type: "run_completed", state: "completed" });
  } else {
    pushFailure(events, runId, timestamp, "failed", outcome);
  }
  return events;
}

function pushTerminalOutcome(
  events: AgentRunEvent[],
  runId: string,
  timestamp: string,
  outcome: WorkbenchOutcome,
  agentTraceId?: string,
  gatewayTraceId?: string
) {
  // S2-A hybrid SSE (Design Doc §SSE 事件): when outcome carries a
  // matchDecision of SHOW_OPTIONS or ESCALATE_TO_PLANNER, emit a
  // dedicated match_decision_created event with a `match-decision` artifact
  // so the Workbench can render the five-state decision view. SELECT /
  // CLARIFY / REJECT reuse the existing capability_selected / narrative_created
  // / run_failed paths and do NOT emit this event.
  pushMatchDecisionEventIfPresent(events, runId, timestamp, outcome);

  if (outcome.responseText) {
    push(events, runId, timestamp, {
      type: "narrative_created",
      state: "narrated",
      artifact: redactArtifact({
        label: "Chinese Narrative",
        kind: "narrative",
        payload: toJsonValue({ text: outcome.responseText })
      })
    });
  }
  if (agentTraceId || gatewayTraceId) {
    push(events, runId, timestamp, {
      type: "trace_linked",
      state: "trace_linked",
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({
        label: "Trace Metadata",
        kind: "trace",
        payload: toJsonValue({ agentTraceId, gatewayTraceId })
      })
    });
  }
  if (outcome.status === "clarification") {
    push(events, runId, timestamp, { type: "run_completed", state: "completed" });
  } else {
    pushFailure(events, runId, timestamp, "intent_parsed", outcome);
  }
}

function pushMatchDecisionEventIfPresent(
  events: AgentRunEvent[],
  runId: string,
  timestamp: string,
  outcome: WorkbenchOutcome
) {
  const matchDecision = objectOrNull(outcome.matchDecision);
  if (!matchDecision) {
    return;
  }
  const decisionType = textValue(matchDecision.decisionType);
  if (decisionType !== "SHOW_OPTIONS" && decisionType !== "ESCALATE_TO_PLANNER") {
    return;
  }
  const candidates = matchDecision.candidates ?? null;
  const handoff = matchDecision.handoff ?? null;
  const rationale = textValue(matchDecision.rationale) ?? "";
  // S2-B (Task 9): fold the DryRunResult into the match-decision artifact
  // payload when present. Only ESCALATE_TO_PLANNER outcomes carry a dry-run
  // (the orchestrator wires the handoff into the PlanCompiler). The
  // Workbench's `buildDryRunView` parses this field to render the dry-run
  // preview (PlanGraph nodes/edges/gaps/governanceFlags) in the same turn.
  const dryRun = objectOrNull(outcome.dryRun);
  push(events, runId, timestamp, {
    type: "match_decision_created",
    state: "match_decided",
    artifact: redactArtifact({
      label: "MatchDecision",
      kind: "match-decision",
      payload: toJsonValue({
        decisionType,
        candidates,
        handoff,
        rationale,
        dryRun
      })
    })
  });
}

function pushFailure(
  events: AgentRunEvent[],
  runId: string,
  timestamp: string,
  stage: AgentRunState,
  outcome: WorkbenchOutcome
) {
  push(events, runId, timestamp, {
    type: "run_failed",
    state: "failed",
    error: {
      errorType: outcome.errorType || "AGENT_RUN_FAILED",
      message: outcome.responseText || outcome.message || "Agent run failed",
      stage
    }
  });
}

function buildApprovalEvents(record: AgentRunRecord, outcome: WorkbenchOutcome, timestamp: string): AgentRunEvent[] {
  const events: AgentRunEvent[] = [];
  const base = record.events.length;
  const pushAll = (event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">) => {
    events.push({ runId: record.runId, sequence: base + events.length + 1, timestamp, ...event });
  };
  const callPlan = objectOrNull(outcome.callPlan) ?? objectOrNull(record.pendingOutcome?.callPlan);
  const execution = objectOrNull(outcome.executionResult);
  const approvalRecord = objectOrNull(outcome.approvalRecord);
  const capabilityId = textValue(callPlan?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId);
  const gatewayTraceId = textValue(outcome.gatewayTraceId) ?? textValue(execution?.traceId);

  if (outcome.status === "rejected") {
    pushAll({ type: "approval_state_changed", state: "rejected", hitlState: "rejected", capabilityId, agentTraceId,
      artifact: approvalRecord ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) }) : undefined });
    return events;
  }
  const approvalStatus = textValue(approvalRecord?.status);
  if (approvalStatus !== "approved" && approvalStatus !== "executed") {
    pushFailureAll(pushAll, "approval_checked", outcome);
    return events;
  }
  pushAll({ type: "approval_state_changed", state: "approval_checked", hitlState: "approved", capabilityId, agentTraceId,
    artifact: approvalRecord ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) }) : undefined });
  if (execution) {
    pushAll({ type: "gateway_execute_started", state: "executing", capabilityId, agentTraceId, gatewayTraceId });
    pushAll({ type: "gateway_execute_completed", state: "executing", capabilityId, agentTraceId, gatewayTraceId,
      artifact: redactArtifact({ label: "ActionResult", kind: "execution-result", payload: toJsonValue(execution) }) });
  }
  if (outcome.responseText) {
    pushAll({ type: "narrative_created", state: "narrated",
      artifact: redactArtifact({ label: "Chinese Narrative", kind: "narrative", payload: toJsonValue({ text: outcome.responseText }) }) });
  }
  if (outcome.status === "success") {
    pushAll({ type: "run_completed", state: "completed", capabilityId, agentTraceId, gatewayTraceId });
  } else {
    pushFailureAll(pushAll, "executing", outcome);
  }
  return events;
}

function pushFailureAll(
  pushAll: (event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">) => void,
  stage: AgentRunState,
  outcome: WorkbenchOutcome
) {
  pushAll({ type: "run_failed", state: "failed", error: { errorType: outcome.errorType || "AGENT_RUN_FAILED", message: outcome.responseText || outcome.message || "Agent run failed", stage } });
}

function buildBatchEvents(record: AgentRunRecord, outcome: WorkbenchOutcome, timestamp: string): AgentRunEvent[] {
  const events: AgentRunEvent[] = [];
  const base = record.events.length;
  const pushAll = (event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">) => {
    events.push({ runId: record.runId, sequence: base + events.length + 1, timestamp, ...event });
  };
  const callPlan = objectOrNull(outcome.callPlan) ?? objectOrNull(record.pendingOutcome?.callPlan);
  const capabilityId = textValue(callPlan?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId);
  const gatewayTraceId = textValue(outcome.gatewayTraceId);

  if (outcome.responseText) {
    pushAll({ type: "narrative_created", state: "narrated",
      artifact: redactArtifact({ label: "Chinese Narrative", kind: "narrative", payload: toJsonValue({ text: outcome.responseText }) }) });
  }
  if (outcome.status === "success") {
    pushAll({ type: "run_completed", state: "completed", capabilityId, agentTraceId, gatewayTraceId });
  } else {
    pushFailureAll(pushAll, "executing", outcome);
  }
  return events;
}

function buildRuntimeFailureEventsTail(runId: string, baseSequence: number, timestamp: string, error: unknown): AgentRunEvent[] {
  const safeMessage = error instanceof Error ? error.message : "Agent runtime failed";
  return [{ runId, sequence: baseSequence + 1, timestamp, type: "run_failed", state: "failed",
    error: { errorType: "AGENT_RUNTIME_ERROR", message: safeMessage, stage: "running" } }];
}

function buildRuntimeFailureEvents(runId: string, timestamp: string, error: unknown): AgentRunEvent[] {
  const safeMessage = error instanceof Error ? error.message : "Agent runtime failed";
  return [
    { runId, sequence: 1, timestamp, type: "run_started", state: "running" },
    {
      runId,
      sequence: 2,
      timestamp,
      type: "run_failed",
      state: "failed",
      error: { errorType: "AGENT_RUNTIME_ERROR", message: safeMessage, stage: "running" }
    }
  ];
}

function push(
  events: AgentRunEvent[],
  runId: string,
  timestamp: string,
  event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">
) {
  events.push({ runId, sequence: events.length + 1, timestamp, ...event });
}

async function runLocalPythonAgent(input: AgentRunnerInput): Promise<WorkbenchOutcome> {
  const repoRoot = repoRootPath();
  const python = pythonExecutable(repoRoot);
  let args: string[];
  let stdinPayload: string | undefined;

  if (input.continuation) {
    const isBatch = input.continuation.type === "batch";
    args = [
      "-m",
      "sap_nexus_agent.cli",
      isBatch ? "--continue-batch" : "--continue-action",
      "--gateway-url",
      input.gatewayUrl,
      "--json"
    ];
    stdinPayload = JSON.stringify(input.continuation);
  } else if (input.context) {
    args = [
      "-m",
      "sap_nexus_agent.cli",
      input.query,
      "--context",
      "--gateway-url",
      input.gatewayUrl,
      "--intent-mode",
      input.intentMode,
      "--json"
    ];
    stdinPayload = JSON.stringify(input.context);
  } else {
    args = [
      "-m",
      "sap_nexus_agent.cli",
      input.query,
      "--gateway-url",
      input.gatewayUrl,
      "--intent-mode",
      input.intentMode,
      "--json"
    ];
  }
  const env = {
    ...process.env,
    PYTHONPATH: [path.join(repoRoot, "agent"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter)
  };

  const { stdout } = await spawnAndCapture(python, args, repoRoot, env, stdinPayload);
  try {
    return JSON.parse(stdout.trim()) as WorkbenchOutcome;
  } catch {
    throw new Error("Agent runner did not produce valid Workbench JSON.");
  }
}

function spawnAndCapture(
  command: string,
  args: string[],
  cwd: string,
  env: NodeJS.ProcessEnv,
  stdinPayload?: string
): Promise<{ stdout: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env });
    let stdout = "";
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", () => {
      // stderr may contain environment-specific details; never forward it to the UI.
    });
    if (stdinPayload !== undefined) {
      child.stdin.end(stdinPayload);
    }
    child.on("error", () => reject(new Error("Agent runner process could not be started.")));
    child.on("close", () => resolve({ stdout }));
  });
}

function repoRootPath() {
  if (process.env.SAP_NEXUS_AGENT_ROOT) {
    return process.env.SAP_NEXUS_AGENT_ROOT;
  }
  const cwd = process.cwd();
  return path.basename(cwd) === "frontend" ? path.dirname(cwd) : cwd;
}

function pythonExecutable(repoRoot: string) {
  if (process.env.SAP_NEXUS_AGENT_PYTHON) {
    return process.env.SAP_NEXUS_AGENT_PYTHON;
  }
  const venvPython = path.join(repoRoot, ".venv", "bin", "python");
  return existsSync(venvPython) ? venvPython : "python3";
}

function gatewayUrl() {
  return process.env.SAP_NEXUS_GATEWAY_URL || `http://127.0.0.1:${process.env.GATEWAY_PORT || "8080"}`;
}

function intentMode() {
  return process.env.SAP_NEXUS_INTENT_MODE || "hybrid";
}

function objectOrNull(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function textValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function toJsonValue(value: unknown): JsonValue {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : String(value);
  }
  if (Array.isArray(value)) {
    return value.map((entry) => toJsonValue(entry));
  }
  if (typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, toJsonValue(entry)]));
  }
  return String(value);
}
