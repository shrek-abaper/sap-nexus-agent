import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import type { AgentRunEvent, AgentRunState } from "./run-event-schema";
import { redactArtifact } from "./redaction";
import type { JsonValue } from "../shared/types/artifacts";

type CreateAgentRunInput = {
  query: string;
  rfcName?: string;
  conversationId?: string;
};

type LastContext = {
  capabilityId: string;
  parameters: Record<string, string>;
  missingParameters: string[];
  decisionType: "CLARIFY" | "SELECT";
};

type Turn = { role: "user" | "assistant"; content: string };

type ConversationContext = {
  lastContext: LastContext | null;
  history: Turn[] | null;
};

type SessionState = {
  lastContext: LastContext | null;
  lastRunId: string | null;
  lastRunStatus: string | null;
  history: Turn[];
};

type AgentRunRecord = {
  runId: string;
  query: string;
  events: AgentRunEvent[];
  pendingOutcome?: WorkbenchOutcome;
  decision?: ApprovalDecision;
};

export type ApprovalDecision = "approve" | "reject";

type ApprovalContinuation = {
  decision: ApprovalDecision;
  callPlan: Record<string, unknown>;
  validationResult: Record<string, unknown>;
  approvalRecord: Record<string, unknown>;
};

type AgentRunnerInput = {
  query: string;
  gatewayUrl: string;
  intentMode: string;
  continuation?: ApprovalContinuation;
  context?: ConversationContext;
};

type WorkbenchOutcome = {
  status: string;
  message?: string | null;
  responseText?: string | null;
  callPlan?: Record<string, unknown> | null;
  validationResult?: Record<string, unknown> | null;
  executionResult?: Record<string, unknown> | null;
  fact?: Record<string, unknown> | null;
  gatewayTraceId?: string | null;
  errorType?: string | null;
  missingParameters?: string[] | null;
  approvalRecord?: Record<string, unknown> | null;
  // Advisory field populated by agent workbench_output (Task 3.3):
  // `{ decisionType, capabilityId?, parameters?, missingParameters?, errorType?,
  // candidates?, handoff?, rationale }`. The SSE layer only emits a
  // `match_decision_created` event for SHOW_OPTIONS / ESCALATE_TO_PLANNER;
  // SELECT / CLARIFY / REJECT reuse the existing event paths (Design Doc D6/Q4
  // hybrid SSE).
  matchDecision?: Record<string, unknown> | null;
  // S2-B dry-run result (Task 9). Populated only for ESCALATE_TO_PLANNER
  // outcomes. Folded into the `match-decision` artifact payload so the
  // Workbench can render the dry-run preview (PlanGraph nodes/edges/gaps/
  // governanceFlags) in the same ESCALATE turn without a new event type.
  dryRun?: Record<string, unknown> | null;
  // Conversational context backfilled by Python outcome_to_workbench_dict
  // (Task 5). Non-null after CLARIFY/SELECT; null after REJECT/ESCALATE or
  // when no capability decision was made. The adapter uses this to update
  // SessionState.lastContext for multi-turn continuity.
  lastContext?: LastContext | null;
};

type AgentRunner = (input: AgentRunnerInput) => Promise<WorkbenchOutcome>;

const globalRunStore = globalThis as typeof globalThis & {
  __SAP_NEXUS_AGENT_RUNS__?: Map<string, AgentRunRecord>;
  __SAP_NEXUS_AGENT_SESSIONS__?: Map<string, SessionState>;
};

// Next route handlers can load this module in separate bundles; keep runs process-wide.
const runs = (globalRunStore.__SAP_NEXUS_AGENT_RUNS__ ??= new Map<string, AgentRunRecord>());
// Conversational sessions keyed by conversationId; parallel to `runs` so a run
// can carry forward the prior turn's lastContext + recent history (Task 7).
const sessions = (globalRunStore.__SAP_NEXUS_AGENT_SESSIONS__ ??= new Map<string, SessionState>());
let runnerForTests: AgentRunner | null = null;

export function setAgentRunnerForTests(runner: AgentRunner | null) {
  runnerForTests = runner;
}

export function resetAgentRunsForTests() {
  runs.clear();
}

export function resetAgentSessionsForTests() {
  sessions.clear();
}

function getSession(conversationId: string): SessionState {
  let session = sessions.get(conversationId);
  if (!session) {
    session = { lastContext: null, lastRunId: null, lastRunStatus: null, history: [] };
    sessions.set(conversationId, session);
  }
  return session;
}

function buildContext(session: SessionState): ConversationContext | undefined {
  if (!session.lastContext) return undefined;
  const recent = session.history.slice(-3);
  return {
    lastContext: session.lastContext,
    history: recent.length > 0 ? recent : null
  };
}

export async function createAgentRun(input: CreateAgentRunInput): Promise<{ runId: string }> {
  if (input.rfcName) {
    throw new Error("Raw RFC execution is not allowed");
  }

  // Q2: reject new queries on a conversation that still has a pending write
  // approval. The user must approve or reject the prior Action before the
  // conversation can accept new input.
  if (input.conversationId) {
    const session = getSession(input.conversationId);
    if (session.lastRunStatus === "awaiting_approval") {
      throw new Error("当前对话有待审批的写操作，请先处理审批后再发起新查询。");
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
  runs.set(runId, record);

  try {
    const runner = runnerForTests ?? runLocalPythonAgent;
    const context = input.conversationId ? buildContext(getSession(input.conversationId)) : undefined;
    const outcome = await runner({ query, gatewayUrl: gatewayUrl(), intentMode: intentMode(), context });
    record.events = buildEventsFromOutcome(runId, query, outcome, timestamp);
    if (outcome.status === "awaiting_approval") {
      record.pendingOutcome = outcome;
    }

    // Backfill session: CLARIFY/SELECT update lastContext; REJECT/ESCALATE and
    // awaiting_approval outcomes carry null lastContext and clear it.
    if (input.conversationId) {
      const session = getSession(input.conversationId);
      session.lastRunId = runId;
      session.lastRunStatus = outcome.status;
      session.history.push({ role: "user", content: query });
      if (outcome.responseText) {
        session.history.push({ role: "assistant", content: outcome.responseText });
      }
      session.lastContext = outcome.lastContext ?? null;
    }
  } catch (error) {
    record.events = buildRuntimeFailureEvents(runId, timestamp, error);
  }

  return { runId };
}

export async function getAgentRunEvents(runId: string): Promise<AgentRunEvent[]> {
  const run = runs.get(runId);
  if (!run) {
    return [];
  }

  return run.events;
}

export async function decideAgentRunApproval(runId: string, decision: ApprovalDecision): Promise<void> {
  const record = runs.get(runId);
  if (!record) {
    throw new Error("Agent run not found");
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

  record.decision = decision;
  const runner = runnerForTests ?? runLocalPythonAgent;
  try {
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { decision, callPlan, validationResult, approvalRecord }
    });
    appendApprovalEvents(record, outcome, new Date().toISOString());
  } catch (error) {
    appendRuntimeFailure(record, error, new Date().toISOString());
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

function appendApprovalEvents(record: AgentRunRecord, outcome: WorkbenchOutcome, timestamp: string) {
  const callPlan = objectOrNull(outcome.callPlan) ?? objectOrNull(record.pendingOutcome?.callPlan);
  const execution = objectOrNull(outcome.executionResult);
  const approvalRecord = objectOrNull(outcome.approvalRecord);
  const capabilityId = textValue(callPlan?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId);
  const gatewayTraceId = textValue(outcome.gatewayTraceId) ?? textValue(execution?.traceId);

  if (outcome.status === "rejected") {
    push(record.events, record.runId, timestamp, {
      type: "approval_state_changed",
      state: "rejected",
      hitlState: "rejected",
      capabilityId,
      agentTraceId,
      artifact: approvalRecord
        ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) })
        : undefined
    });
    return;
  }

  const approvalStatus = textValue(approvalRecord?.status);
  if (approvalStatus !== "approved" && approvalStatus !== "executed") {
    pushFailure(record.events, record.runId, timestamp, "approval_checked", outcome);
    return;
  }

  push(record.events, record.runId, timestamp, {
    type: "approval_state_changed",
    state: "approval_checked",
    hitlState: "approved",
    capabilityId,
    agentTraceId,
    artifact: approvalRecord
      ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) })
      : undefined
  });

  if (execution) {
    push(record.events, record.runId, timestamp, {
      type: "gateway_execute_started",
      state: "executing",
      capabilityId,
      agentTraceId,
      gatewayTraceId
    });
    push(record.events, record.runId, timestamp, {
      type: "gateway_execute_completed",
      state: "executing",
      capabilityId,
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({ label: "ActionResult", kind: "execution-result", payload: toJsonValue(execution) })
    });
  }

  if (outcome.responseText) {
    push(record.events, record.runId, timestamp, {
      type: "narrative_created",
      state: "narrated",
      artifact: redactArtifact({
        label: "Chinese Narrative",
        kind: "narrative",
        payload: toJsonValue({ text: outcome.responseText })
      })
    });
  }
  if (outcome.status === "success") {
    push(record.events, record.runId, timestamp, {
      type: "run_completed",
      state: "completed",
      capabilityId,
      agentTraceId,
      gatewayTraceId
    });
  } else {
    pushFailure(record.events, record.runId, timestamp, "executing", outcome);
  }
}

function appendRuntimeFailure(record: AgentRunRecord, error: unknown, timestamp: string) {
  const safeMessage = error instanceof Error ? error.message : "Agent runtime failed";
  push(record.events, record.runId, timestamp, {
    type: "run_failed",
    state: "failed",
    error: { errorType: "AGENT_RUNTIME_ERROR", message: safeMessage, stage: "running" }
  });
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
    args = [
      "-m",
      "sap_nexus_agent.cli",
      "--continue-action",
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
