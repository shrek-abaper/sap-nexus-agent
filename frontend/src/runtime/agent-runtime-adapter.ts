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
  SessionStateV2,
  WorkbenchOutcome
} from "./durable/types";
import { JsonlConversationStore } from "./durable/jsonl-conversation-store";
import { JsonlRunStore } from "./durable/jsonl-run-store";
import { canonicalJson, sha256Hex } from "./durable/canonical-json";
import { idempotencyKey } from "./durable/idempotency";
import type { ContinuationType } from "./durable/types";
import type { TrustedPrincipal } from "./principal/types";
import {
  PlanActionContinuation,
  hasDurablePlanActionEnvelope,
  planApprovalOwnership,
  type ActionGateway,
  type ActionGovernanceInput,
  type PlanApprovalRecord,
} from "./action-governance/action-governance";
import { createServerActionGateway } from "./action-governance/server-action-gateway";
import type { GatewayClient } from "./plan-executor/types";
import { CompositionCoordinator } from "./composition/coordinator";
import { parseCompositionHandoff } from "./composition/handoff";
import { createServerReadGateway } from "./composition/server-read-gateway";

export type { ApprovalDecision } from "./durable/types";

import { redactArtifact } from "./redaction";
import type { JsonValue } from "../shared/types/artifacts";

export type CreateAgentRunInput = {
  query: string;
  rfcName?: string;
  conversationId?: string;
  turnId?: string;
  principal: TrustedPrincipal;
};

export type CreateAgentRunResult = { runId: string; turnId: string };

export class ConversationProtocolError extends Error {
  constructor(
    readonly code: "CONVERSATION_BUSY" | "CONTEXT_VERSION_CONFLICT" | "CONVERSATION_TURN_IN_FLIGHT",
    message: string,
  ) {
    super(message);
    this.name = "ConversationProtocolError";
  }
}

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
  principal?: TrustedPrincipal;
};

type AgentRunner = (input: AgentRunnerInput) => Promise<WorkbenchOutcome>;

type AsyncPush = (event: Omit<AgentRunEvent, "runId" | "sequence" | "timestamp">) => Promise<void>;

const workbenchDataDir = process.env.WORKBENCH_DATA_DIR ?? path.join(process.cwd(), ".workbench-data");
const durableDataDir = path.join(workbenchDataDir, "durable");
const workerId = process.env.WORKER_ID ?? `worker-${process.pid}`;
const CONVERSATION_LEASE_TTL_MS = 60_000;
const CONVERSATION_LEASE_HEARTBEAT_MS = 20_000;

let runStore: DurableRunStore = new JsonlRunStore(durableDataDir, workerId);
let conversationStore: DurableConversationStore = new JsonlConversationStore(durableDataDir);
let runnerForTests: AgentRunner | null = null;
let compositionGatewayForTests: GatewayClient | null = null;
let planActionGatewayForTests: ActionGateway | null = null;

export function setAgentRunnerForTests(runner: AgentRunner | null) {
  runnerForTests = runner;
}

export function setCompositionGatewayForTests(gateway: GatewayClient | null) {
  compositionGatewayForTests = gateway;
}

export function setPlanActionGatewayForTests(gateway: ActionGateway | null) {
  planActionGatewayForTests = gateway;
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

async function getSession(conversationId: string, principalId: string): Promise<SessionStateV2> {
  return await conversationStore.load(conversationId, principalId) ?? newSession(principalId);
}

function newSession(principalId: string): SessionStateV2 {
  return {
    schemaVersion: 2,
    stateVersion: 0,
    principalId,
    activeFrame: null,
    recentFrames: [],
    pendingInteraction: null,
    history: [],
    lastAppliedTurnId: null,
    lastRunId: null,
  };
}

function buildContext(session: SessionStateV2): ConversationContext | undefined {
  // Align with Python llm_intent.py `context.history[-6:]`: 近 3 轮 =
  // user+assistant = 6 条 Turn (Concern 3).
  const recent = session.history.slice(-6);
  if (recent.length === 0) return undefined;
  return {
    // Persisted legacy context is never promoted back into execution authority.
    lastContext: null,
    history: recent,
  };
}

export async function createAgentRun(input: CreateAgentRunInput): Promise<CreateAgentRunResult> {
  if (input.rfcName) {
    throw new Error("Raw RFC execution is not allowed");
  }
  const turnId = input.turnId ?? `turn-${crypto.randomUUID()}`;
  if (!turnId) throw new Error("turnId must be a non-empty string");

  if (!input.conversationId) {
    const runId = await startAgentRun(input.query, input.principal);
    void executeRunnerInBackground(
      runId,
      input.query,
      undefined,
      new Date().toISOString(),
      input.principal.principalId,
      input.principal,
    );
    return { runId, turnId };
  }

  const conversationId = input.conversationId;
  const conversationLeaseOwner = `${workerId}:conversation:${crypto.randomUUID()}`;
  const lease = await conversationStore.claim(
    conversationId,
    conversationLeaseOwner,
    CONVERSATION_LEASE_TTL_MS,
  );
  if (lease.status === "rejected") {
    throw new ConversationProtocolError(
      "CONVERSATION_BUSY",
      `Conversation is held by another worker (${lease.holder})`,
    );
  }

  let backgroundOwnsLease = false;
  try {
    const priorTurn = await conversationStore.lookupTurn(
      conversationId,
      input.principal.principalId,
      turnId,
    );
    if (priorTurn) {
      const prior = await runStore.load(priorTurn.runId);
      if (prior && isTerminalRun(prior)) {
        return { runId: prior.runId, turnId };
      }
      throw new ConversationProtocolError(
        "CONVERSATION_TURN_IN_FLIGHT",
        "The turn was persisted but has no terminal result; automatic READ replay is disabled",
      );
    }
    const session = await getSession(conversationId, input.principal.principalId);

    const lastRunId = session.lastRunId;
    if (lastRunId) {
      const lastRun = await runStore.load(lastRunId);
      if (lastRun?.pendingOutcome && !lastRun.decision) {
        throw new Error("当前对话有待审批的写操作，请先处理审批后再发起新查询。");
      }
    }

    const runId = `run-${crypto.randomUUID()}`;
    const nextSession: SessionStateV2 = {
      ...session,
      stateVersion: session.stateVersion + 1,
      history: [...session.history, { role: "user", content: input.query }],
      lastAppliedTurnId: turnId,
      lastRunId: runId,
    };
    const saved = await conversationStore.compareAndSwap(
      conversationId,
      session.stateVersion,
      nextSession,
      { workerId: conversationLeaseOwner, fenceToken: lease.fenceToken },
    );
    if (saved.status === "lease-lost") {
      throw new ConversationProtocolError(
        "CONVERSATION_BUSY",
        `Conversation lease ownership was lost${saved.holder ? ` to ${saved.holder}` : ""}`,
      );
    }
    if (saved.status === "conflict") {
      throw new ConversationProtocolError(
        "CONTEXT_VERSION_CONFLICT",
        `Conversation state changed from version ${session.stateVersion} to ${saved.actualVersion}`,
      );
    }

    const timestamp = new Date().toISOString();
    await persistStartedRun(runId, input.query, input.principal, timestamp);
    const context = buildContext(session);
    backgroundOwnsLease = true;
    void executeRunnerInBackground(
      runId,
      input.query,
      conversationId,
      timestamp,
      input.principal.principalId,
      input.principal,
      turnId,
      nextSession.stateVersion,
      conversationLeaseOwner,
      lease.fenceToken,
      context,
    );

    return { runId, turnId };
  } finally {
    if (!backgroundOwnsLease) {
      await conversationStore.release(conversationId, conversationLeaseOwner, lease.fenceToken);
    }
  }
}

async function startAgentRun(
  query: string,
  principal: TrustedPrincipal,
): Promise<string> {
  const runId = `run-${crypto.randomUUID()}`;
  await persistStartedRun(runId, query, principal, new Date().toISOString());
  return runId;
}

async function persistStartedRun(
  runId: string,
  query: string,
  principal: TrustedPrincipal,
  timestamp: string,
): Promise<void> {
  const record: AgentRunRecord = {
    runId,
    query,
    events: [{ runId, sequence: 1, timestamp, type: "run_started", state: "running" }],
    principalId: principal.principalId,
  };
  await runStore.save(runId, record);
  await runStore.claim(runId, workerId, 60_000);
}

async function executeRunnerInBackground(
  runId: string,
  query: string,
  conversationId: string | undefined,
  timestamp: string,
  principalId: string,
  principal?: TrustedPrincipal,
  turnId?: string,
  expectedSessionVersion?: number,
  conversationLeaseOwner?: string,
  conversationFenceToken?: string,
  context?: ConversationContext,
): Promise<void> {
  let heartbeat: ReturnType<typeof startConversationLeaseHeartbeat> | null = null;
  try {
    heartbeat = conversationId && conversationLeaseOwner && conversationFenceToken
      ? startConversationLeaseHeartbeat(conversationId, conversationLeaseOwner, conversationFenceToken)
      : null;
    if (heartbeat) await heartbeat.assertOwned();
    const runner = runnerForTests ?? runLocalPythonAgent;
    const outcome = await runner({ query, gatewayUrl: gatewayUrl(), intentMode: intentMode(), context, principal });
    if (heartbeat) await heartbeat.assertOwned();
    const handoff = parseCompositionHandoff(outcome);
    let sessionOutcome = outcome;
    if (handoff) {
      const composition = await new CompositionCoordinator({
        store: runStore,
        gateway: compositionGatewayForTests ?? createServerReadGateway(),
        workerId,
      }).execute({
        runId,
        traceId: `trace-${runId}`,
        principal: principal ?? {
          principalId,
          role: "operator",
          dataScope: { tenantId: "default" },
        },
        handoff,
      });
      if (composition.actionGovernanceInput) {
        const approval = await planActionRuntime().prepare(composition.actionGovernanceInput);
        sessionOutcome = {
          status: "awaiting_approval",
          responseText: composition.narrative.summary,
          approvalRecord: approval as unknown as Record<string, unknown>,
        };
      } else {
        sessionOutcome = {
          status: "success",
          responseText: composition.narrative.summary,
        };
      }
    }

    if (conversationId && turnId && expectedSessionVersion !== undefined) {
      if (!heartbeat) {
        throw new ConversationProtocolError(
          "CONVERSATION_BUSY",
          "Conversation lease binding is missing before result persistence",
        );
      }
      await heartbeat.assertOwned();
      const session = await getSession(conversationId, principalId);
      if (session.stateVersion !== expectedSessionVersion ||
          session.lastAppliedTurnId !== turnId || session.lastRunId !== runId) {
        throw new ConversationProtocolError(
          "CONTEXT_VERSION_CONFLICT",
          "Conversation binding changed before the run result could be persisted",
        );
      }
      const nextHistory = [...session.history];
      if (sessionOutcome.responseText) {
        nextHistory.push({ role: "assistant", content: sessionOutcome.responseText });
      }
      const nextSession: SessionStateV2 = {
        ...session,
        stateVersion: session.stateVersion + 1,
        history: nextHistory,
      };
      const saved = await conversationStore.compareAndSwap(
        conversationId,
        session.stateVersion,
        nextSession,
        {
          workerId: conversationLeaseOwner!,
          fenceToken: conversationFenceToken!,
        },
      );
      if (saved.status === "lease-lost") {
        throw new ConversationProtocolError(
          "CONVERSATION_BUSY",
          `Conversation lease ownership was lost${saved.holder ? ` to ${saved.holder}` : ""}`,
        );
      }
      if (saved.status === "conflict") {
        throw new ConversationProtocolError(
          "CONTEXT_VERSION_CONFLICT",
          `Conversation result lost CAS at version ${saved.actualVersion}`,
        );
      }
    }

    if (!handoff) {
      await emitEventsFromOutcome(runId, query, outcome, timestamp,
        (event) => runStore.appendEvent(runId, event), 2);

      if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
        await runStore.appendPendingOutcome(runId, outcome);
      }
    }
  } catch (error) {
    const currentRecord = await runStore.load(runId);
    if (!currentRecord) return;
    const baseSeq = currentRecord.events.length;
    const failEvents = buildRuntimeFailureEventsTail(runId, baseSeq, new Date().toISOString(), error);
    for (const event of failEvents) {
      await runStore.appendEvent(runId, event);
    }
  } finally {
    heartbeat?.stop();
    await runStore.release(runId, workerId);
    if (conversationId && conversationLeaseOwner && conversationFenceToken) {
      await conversationStore.release(
        conversationId,
        conversationLeaseOwner,
        conversationFenceToken,
      );
    }
  }
}

function startConversationLeaseHeartbeat(
  conversationId: string,
  owner: string,
  fenceToken: string,
): { assertOwned: () => Promise<void>; stop: () => void } {
  let stopped = false;
  let lost: Error | null = null;
  let renewal: Promise<void> | null = null;

  const renew = async (): Promise<void> => {
    if (stopped || lost) return;
    const outcome = await conversationStore.renew(
      conversationId,
      owner,
      fenceToken,
      CONVERSATION_LEASE_TTL_MS,
    );
    if (outcome.status === "lost") {
      lost = new ConversationProtocolError(
        "CONVERSATION_BUSY",
        `Conversation lease ownership was lost${outcome.holder ? ` to ${outcome.holder}` : ""}`,
      );
    }
  };
  const scheduleRenewal = () => {
    if (renewal || stopped || lost) return;
    renewal = renew()
      .catch((error: unknown) => {
        lost = error instanceof Error ? error : new Error(String(error));
      })
      .finally(() => { renewal = null; });
  };
  const timer = setInterval(scheduleRenewal, CONVERSATION_LEASE_HEARTBEAT_MS);
  timer.unref?.();

  return {
    assertOwned: async () => {
      if (renewal) await renewal;
      if (lost) throw lost;
      await renew();
      if (lost) throw lost;
    },
    stop: () => {
      stopped = true;
      clearInterval(timer);
    },
  };
}

function isTerminalRun(record: AgentRunRecord): boolean {
  const last = record.events[record.events.length - 1];
  return last?.type === "run_completed" || last?.type === "run_failed";
}

export async function getAgentRunEvents(
  runId: string,
  principal: TrustedPrincipal
): Promise<AgentRunEvent[]> {
  const run = await runStore.load(runId);
  if (!run || run.principalId !== principal.principalId) return [];
  if (planApprovalOwnership(run.pendingOutcome, principal) === false) return [];
  return run.events;
}

export async function prepareAgentRunPlanAction(
  input: ActionGovernanceInput,
): Promise<PlanApprovalRecord> {
  return planActionRuntime().prepare(input);
}

export async function decideAgentRunApproval(
  runId: string,
  approvalId: string,
  decision: ApprovalDecision,
  principal: TrustedPrincipal
): Promise<void> {
  const record = await runStore.load(runId);
  if (!record || record.principalId !== principal.principalId) {
    throw new Error("Agent run not found");
  }

  const approvalRecordForIdem = objectOrNull(record.pendingOutcome?.approvalRecord);
  const serverApprovalId = textValue(approvalRecordForIdem?.approvalId)
    ?? textValue(approvalRecordForIdem?.id);
  if (!serverApprovalId || serverApprovalId !== approvalId) {
    throw new Error("Agent run approval identity does not match the pending record");
  }

  if (hasDurablePlanActionEnvelope(record.pendingOutcome)) {
    const runtime = planActionRuntime();
    const outcome = await runtime.recordDecision(runId, approvalId, decision, principal, new Date().toISOString());
    if (decision === "approve" && outcome.status === "approved") {
      void executePlanActionInBackground(runtime, runId, approvalId, principal);
    }
    return;
  }

  // idempotency: a retried continuation returns the already-recorded result
  // without re-executing. Checked before the pendingOutcome/decision guards so
  // a duplicate request is a no-op rather than an "already decided" error.
  const continuationType: ContinuationType = decision === "approve" ? "approval_approve" : "approval_reject";
  const idemKey = idempotencyKey(runId, continuationType, { decision, approvalRecordId: serverApprovalId });
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
  // §1.3: fire-and-forget background execution; return immediately
  void executeApprovalInBackground(runId, record, decision, callPlan, validationResult, approvalRecord, idemKey);
}

async function executeApprovalInBackground(
  runId: string,
  record: AgentRunRecord,
  decision: ApprovalDecision,
  callPlan: Record<string, unknown>,
  validationResult: Record<string, unknown>,
  approvalRecord: Record<string, unknown>,
  idemKey: string
): Promise<void> {
  try {
    const runner = runnerForTests ?? runLocalPythonAgent;
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { decision, callPlan, validationResult, approvalRecord }
    });
    await emitApprovalEvents(record, outcome, new Date().toISOString(),
      (event) => runStore.appendEvent(runId, event));
    await runStore.markExecuted(idemKey, outcome);
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      await runStore.release(runId, workerId);
    }
  } catch (error) {
    const currentRecord = await runStore.load(runId);
    const baseSeq = currentRecord?.events.length ?? record.events.length;
    const failEvents = buildRuntimeFailureEventsTail(runId, baseSeq, new Date().toISOString(), error);
    for (const event of failEvents) {
      await runStore.appendEvent(runId, event);
    }
    await runStore.release(runId, workerId);
  }
}

export async function confirmAgentRunBatch(
  runId: string,
  principal: TrustedPrincipal
): Promise<void> {
  const record = await runStore.load(runId);
  if (!record || record.principalId !== principal.principalId) {
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
  // §1.3: fire-and-forget background execution; return immediately
  void executeBatchInBackground(runId, record, callPlan, combinations, idemKey);
}

async function executeBatchInBackground(
  runId: string,
  record: AgentRunRecord,
  callPlan: Record<string, unknown>,
  combinations: Record<string, string>[],
  idemKey: string
): Promise<void> {
  try {
    const runner = runnerForTests ?? runLocalPythonAgent;
    const outcome = await runner({
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      continuation: { type: "batch", callPlan, combinations }
    });
    await emitBatchEvents(record, outcome, new Date().toISOString(),
      (event) => runStore.appendEvent(runId, event));
    await runStore.markExecuted(idemKey, outcome);
    if (outcome.status === "awaiting_approval" || outcome.status === "awaiting_batch_confirm") {
      await runStore.release(runId, workerId);
    }
  } catch (error) {
    const currentRecord = await runStore.load(runId);
    const baseSeq = currentRecord?.events.length ?? record.events.length;
    const failEvents = buildRuntimeFailureEventsTail(runId, baseSeq, new Date().toISOString(), error);
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

async function emitEventsFromOutcome(
  runId: string,
  query: string,
  outcome: WorkbenchOutcome,
  timestamp: string,
  emit: (event: AgentRunEvent) => Promise<void>,
  nextSequence: number
): Promise<void> {
  let seq = nextSequence;
  const push: AsyncPush = async (event) => {
    await emit({ runId, sequence: seq, timestamp, ...event });
    seq++;
  };

  const callPlan = objectOrNull(outcome.callPlan);
  const validation = objectOrNull(outcome.validationResult);
  const execution = objectOrNull(outcome.executionResult);
  const fact = objectOrNull(outcome.fact);
  const capabilityId = textValue(callPlan?.capabilityId) ?? textValue(validation?.capabilityId) ?? textValue(execution?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId) ?? textValue(fact?.agentTraceId);
  const gatewayTraceId =
    textValue(outcome.gatewayTraceId) ?? textValue(execution?.traceId) ?? textValue(validation?.traceId);

  await push({
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
    await emitTerminalOutcome(push, outcome, agentTraceId, gatewayTraceId);
    return;
  }

  await push({
    type: "capability_selected",
    state: "capability_selected",
    capabilityId,
    artifact: redactArtifact({
      label: "Capability Selection",
      kind: "capability",
      payload: toJsonValue({ capabilityId, kind: callPlan.kind ?? "Function" })
    })
  });
  await push({
    type: "callplan_created",
    state: "callplan_created",
    capabilityId,
    agentTraceId,
    artifact: redactArtifact({ label: "CallPlan", kind: "callplan", payload: toJsonValue(callPlan) })
  });
  const isAction = callPlan.kind === "Action";
  if (!isAction) {
    await push({
      type: "approval_state_changed",
      state: "approval_checked",
      hitlState: "approval_not_required"
    });
  }

  if (validation) {
    await push({
      type: "gateway_validate_started",
      state: "validating",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(validation.traceId) ?? gatewayTraceId
    });
    await push({
      type: "gateway_validate_completed",
      state: "validating",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(validation.traceId) ?? gatewayTraceId,
      artifact: redactArtifact({ label: "Gateway Validation", kind: "validation", payload: toJsonValue(validation) })
    });
    if (validation.success === false) {
      await emitFailure(push, "validating", outcome);
      return;
    }
  }

  if (isAction && outcome.status === "awaiting_approval") {
    const approvalRecord = objectOrNull(outcome.approvalRecord);
    await push({
      type: "approval_state_changed",
      state: "awaiting_approval",
      hitlState: "approval_required"
    });
    await push({
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
    return;
  }

  if (outcome.status === "awaiting_batch_confirm") {
    const combinations = outcome.combinations ?? null;
    await push({
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
    return;
  }

  if (execution) {
    await push({
      type: "gateway_execute_started",
      state: "executing",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(execution.traceId) ?? gatewayTraceId
    });
    await push({
      type: "gateway_execute_completed",
      state: "executing",
      capabilityId,
      agentTraceId,
      gatewayTraceId: textValue(execution.traceId) ?? gatewayTraceId,
      artifact: redactArtifact({ label: "ExecutionResult", kind: "execution-result", payload: toJsonValue(execution) })
    });
    if (execution.success === false) {
      await emitFailure(push, "executing", outcome);
      return;
    }
  }

  if (fact) {
    await push({
      type: "reasoning_fact_created",
      state: "fact_created",
      capabilityId,
      agentTraceId,
      gatewayTraceId,
      artifact: redactArtifact({ label: "ReasoningFact", kind: "reasoning-fact", payload: toJsonValue(fact) })
    });
  }

  if (outcome.responseText) {
    await push({
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
    await push({
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
    await push({ type: "run_completed", state: "completed" });
  } else {
    await emitFailure(push, "failed", outcome);
  }
}

async function emitTerminalOutcome(
  push: AsyncPush,
  outcome: WorkbenchOutcome,
  agentTraceId?: string,
  gatewayTraceId?: string
): Promise<void> {
  await emitMatchDecisionEventIfPresent(push, outcome);

  if (outcome.responseText) {
    await push({
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
    await push({
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
    await push({ type: "run_completed", state: "completed" });
  } else {
    await emitFailure(push, "intent_parsed", outcome);
  }
}

async function emitMatchDecisionEventIfPresent(
  push: AsyncPush,
  outcome: WorkbenchOutcome
): Promise<void> {
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
  const dryRun = objectOrNull(outcome.dryRun);
  await push({
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

async function emitFailure(
  push: AsyncPush,
  stage: AgentRunState,
  outcome: WorkbenchOutcome
): Promise<void> {
  await push({
    type: "run_failed",
    state: "failed",
    error: {
      errorType: outcome.errorType || "AGENT_RUN_FAILED",
      message: outcome.responseText || outcome.message || "Agent run failed",
      stage
    }
  });
}

async function emitApprovalEvents(
  record: AgentRunRecord,
  outcome: WorkbenchOutcome,
  timestamp: string,
  emit: (event: AgentRunEvent) => Promise<void>
): Promise<void> {
  let seq = record.events.length + 1;
  const push: AsyncPush = async (event) => {
    await emit({ runId: record.runId, sequence: seq, timestamp, ...event });
    seq++;
  };
  const callPlan = objectOrNull(outcome.callPlan) ?? objectOrNull(record.pendingOutcome?.callPlan);
  const execution = objectOrNull(outcome.executionResult);
  const approvalRecord = objectOrNull(outcome.approvalRecord);
  const capabilityId = textValue(callPlan?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId);
  const gatewayTraceId = textValue(outcome.gatewayTraceId) ?? textValue(execution?.traceId);

  if (outcome.status === "rejected") {
    await push({ type: "approval_state_changed", state: "rejected", hitlState: "rejected", capabilityId, agentTraceId,
      artifact: approvalRecord ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) }) : undefined });
    // §4.4: append run_failed terminal so the stream can close on rejection
    await push({ type: "run_failed", state: "failed",
      error: { errorType: "APPROVAL_REJECTED", message: outcome.responseText || outcome.message || "Approval rejected", stage: "approval_checked" } });
    return;
  }
  const approvalStatus = textValue(approvalRecord?.status);
  if (approvalStatus !== "approved" && approvalStatus !== "executed") {
    await emitFailure(push, "approval_checked", outcome);
    return;
  }
  await push({ type: "approval_state_changed", state: "approval_checked", hitlState: "approved", capabilityId, agentTraceId,
    artifact: approvalRecord ? redactArtifact({ label: "ApprovalRecord", kind: "approval", payload: toJsonValue(approvalRecord) }) : undefined });
  if (execution) {
    await push({ type: "gateway_execute_started", state: "executing", capabilityId, agentTraceId, gatewayTraceId });
    await push({ type: "gateway_execute_completed", state: "executing", capabilityId, agentTraceId, gatewayTraceId,
      artifact: redactArtifact({ label: "ActionResult", kind: "execution-result", payload: toJsonValue(execution) }) });
  }
  if (outcome.responseText) {
    await push({ type: "narrative_created", state: "narrated",
      artifact: redactArtifact({ label: "Chinese Narrative", kind: "narrative", payload: toJsonValue({ text: outcome.responseText }) }) });
  }
  if (outcome.status === "success") {
    await push({ type: "run_completed", state: "completed", capabilityId, agentTraceId, gatewayTraceId });
  } else {
    await emitFailure(push, "executing", outcome);
  }
}

async function emitBatchEvents(
  record: AgentRunRecord,
  outcome: WorkbenchOutcome,
  timestamp: string,
  emit: (event: AgentRunEvent) => Promise<void>
): Promise<void> {
  let seq = record.events.length + 1;
  const push: AsyncPush = async (event) => {
    await emit({ runId: record.runId, sequence: seq, timestamp, ...event });
    seq++;
  };
  const callPlan = objectOrNull(outcome.callPlan) ?? objectOrNull(record.pendingOutcome?.callPlan);
  const capabilityId = textValue(callPlan?.capabilityId);
  const agentTraceId = textValue(callPlan?.agentTraceId);
  const gatewayTraceId = textValue(outcome.gatewayTraceId);

  if (outcome.responseText) {
    await push({ type: "narrative_created", state: "narrated",
      artifact: redactArtifact({ label: "Chinese Narrative", kind: "narrative", payload: toJsonValue({ text: outcome.responseText }) }) });
  }
  if (outcome.status === "success") {
    await push({ type: "run_completed", state: "completed", capabilityId, agentTraceId, gatewayTraceId });
  } else {
    await emitFailure(push, "executing", outcome);
  }
}

function buildRuntimeFailureEventsTail(runId: string, baseSequence: number, timestamp: string, error: unknown): AgentRunEvent[] {
  const safeMessage = error instanceof Error ? error.message : "Agent runtime failed";
  return [{ runId, sequence: baseSequence + 1, timestamp, type: "run_failed", state: "failed",
    error: {
      errorType: error instanceof ConversationProtocolError ? error.code : "AGENT_RUNTIME_ERROR",
      message: safeMessage,
      stage: "running",
    } }];
}

function planActionRuntime(): PlanActionContinuation {
  return new PlanActionContinuation(
    runStore,
    planActionGatewayForTests ?? createServerActionGateway(),
    workerId,
  );
}

async function executePlanActionInBackground(
  runtime: PlanActionContinuation,
  runId: string,
  approvalId: string,
  principal: TrustedPrincipal,
): Promise<void> {
  try {
    await runtime.executeDurable(runId, approvalId, principal, new Date().toISOString());
  } catch (error) {
    const record = await runStore.load(runId);
    const events = buildRuntimeFailureEventsTail(
      runId,
      record?.events.length ?? 0,
      new Date().toISOString(),
      error,
    );
    for (const event of events) {
      await runStore.appendEvent(runId, event);
    }
    await runStore.release(runId, workerId);
  }
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
    PYTHONPATH: [path.join(repoRoot, "agent"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    ...(input.principal ? { SAP_NEXUS_PRINCIPAL: JSON.stringify(input.principal) } : {})
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
