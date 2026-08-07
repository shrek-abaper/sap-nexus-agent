import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import type { AgentRunEvent, AgentRunState } from "./run-event-schema";
import type {
  AgentRunRecord,
  ApprovalDecision,
  ConversationReadState,
  ConversationContext,
  DurableConversationStore,
  DurableRunStore,
  ReadExecutionBinding,
  SelectionExecutionBinding,
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
  readExecutionBinding: ReadExecutionBinding;
  persistedReadState: ConversationReadState;
};

type AgentRunnerInput = {
  mode: "resolve-read" | "continue-read" | "continue-selection" | "continue-action" | "continue-batch" | "preflight-batch";
  query: string;
  gatewayUrl: string;
  intentMode: string;
  continuation?: ApprovalContinuation | BatchContinuation;
  context?: ConversationContext;
  principal?: TrustedPrincipal;
  turnId?: string;
  callPlan?: Record<string, unknown>;
  readExecutionBinding?: ReadExecutionBinding;
  selectionExecutionBinding?: SelectionExecutionBinding;
  persistedReadState?: ConversationReadState;
  signal?: AbortSignal;
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
let readRunnerForTests: AgentRunner | null = null;
let compositionGatewayForTests: GatewayClient | null = null;
let planActionGatewayForTests: ActionGateway | null = null;

export function setAgentRunnerForTests(runner: AgentRunner | null) {
  runnerForTests = runner;
}

export function setReadAgentRunnerForTests(runner: AgentRunner | null) {
  readRunnerForTests = runner;
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

function buildContext(session: SessionStateV2): ConversationContext {
  // Align with Python llm_intent.py `context.history[-6:]`: 近 3 轮 =
  // user+assistant = 6 条 Turn (Concern 3).
  const recent = session.history.slice(-6);
  return {
    // Persisted legacy context is never promoted back into execution authority.
    lastContext: null,
    history: recent.length > 0 ? recent : null,
    schemaVersion: 2,
    readState: {
      activeFrame: session.activeFrame,
      recentFrames: session.recentFrames,
      pendingInteraction: session.pendingInteraction,
      stateVersion: session.stateVersion,
    },
  };
}

function hasLiveUndecidedBatchPending(
  outcome: WorkbenchOutcome,
  session: SessionStateV2,
  conversationId: string,
  runId: string,
  principalId: string,
): boolean {
  const binding = outcome.batchConversationBinding;
  const pending = session.pendingInteraction;
  const frame = session.activeFrame;
  const callPlan = objectOrNull(outcome.callPlan);
  const combinations = outcome.combinations;
  if (
    outcome.status !== "awaiting_batch_confirm"
    || !binding
    || pending?.kind !== "BATCH_CONFIRMATION"
    || !frame
    || !callPlan
    || !combinations
  ) {
    return false;
  }
  const expectedBatchRef = `sha256:${sha256Hex(canonicalJson({ callPlan, combinations }))}`;
  return session.principalId === principalId
    && session.lastRunId === runId
    && session.lastAppliedTurnId === binding.turnId
    && session.stateVersion === binding.stateVersion
    && binding.conversationId === conversationId
    && binding.principalId === principalId
    && pending.frameId === binding.frameId
    && pending.stateVersion === binding.stateVersion
    && pending.registrySnapshotId === binding.registrySnapshotId
    && pending.batchRef === binding.batchRef
    && pending.batchRef === expectedBatchRef
    && Date.parse(pending.expiresAt) > Date.now()
    && frame.frameId === binding.frameId
    && frame.status === "READY"
    && frame.registrySnapshotId === binding.registrySnapshotId
    && frame.capabilityVersion === binding.capabilityVersion
    && frame.capabilityId === callPlan.capabilityId
    && callPlan.kind === "Function"
    && callPlan.requiresApproval === false
    && sha256Hex(canonicalJson(callPlan)) === binding.callPlanHash;
}

async function hasCurrentBatchAuthority(
  outcome: WorkbenchOutcome,
  session: SessionStateV2,
  principal: TrustedPrincipal,
): Promise<boolean> {
  const callPlan = objectOrNull(outcome.callPlan);
  const combinations = outcome.combinations;
  const binding = outcome.readExecutionBinding;
  if (!callPlan || !combinations || !binding) return true;
  try {
    const runner = readRunnerForTests ?? runLocalPythonAgent;
    const result = await runner({
      mode: "preflight-batch",
      query: "",
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      principal,
      continuation: {
        type: "batch",
        callPlan,
        combinations,
        readExecutionBinding: binding,
        persistedReadState: {
          activeFrame: session.activeFrame,
          recentFrames: session.recentFrames,
          pendingInteraction: session.pendingInteraction,
          stateVersion: session.stateVersion,
        },
      },
    });
    const authority = objectOrNull(result.resolutionReport?.batchAuthority);
    const batchBinding = outcome.batchConversationBinding;
    return authority?.valid === true
      && authority.governanceValid === true
      && authority.snapshotId === batchBinding?.registrySnapshotId
      && authority.capabilityVersion === batchBinding?.capabilityVersion
      && authority.executorBindingId === batchBinding?.executorBindingId;
  } catch {
    // An unavailable preflight must not open a pending batch by accident.
    return true;
  }
}

export async function createAgentRun(input: CreateAgentRunInput): Promise<CreateAgentRunResult> {
  if (input.rfcName) {
    throw new Error("Raw RFC execution is not allowed");
  }
  const turnId = input.turnId ?? `turn-${crypto.randomUUID()}`;
  if (!turnId) throw new Error("turnId must be a non-empty string");

  const conversationId = input.conversationId ?? `conversation-${crypto.randomUUID()}`;
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
        const locallyLiveBatch = lastRun.pendingOutcome.status === "awaiting_batch_confirm"
          && hasLiveUndecidedBatchPending(
            lastRun.pendingOutcome,
            session,
            conversationId,
            lastRunId,
            input.principal.principalId,
          );
        const recoverableBatch = lastRun.pendingOutcome.status === "awaiting_batch_confirm"
          && (!locallyLiveBatch || !await hasCurrentBatchAuthority(
            lastRun.pendingOutcome,
            session,
            input.principal,
          ));
        if (!recoverableBatch) {
          throw new Error("当前对话有待审批的写操作，请先处理审批后再发起新查询。");
        }
      }
    }

    const runId = `run-${crypto.randomUUID()}`;
    const authoritativeRead = true;
    let expectedSessionVersion = session.stateVersion;

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
      expectedSessionVersion,
      conversationLeaseOwner,
      lease.fenceToken,
      context,
      authoritativeRead,
      input.conversationId === undefined,
    );

    return { runId, turnId };
  } finally {
    if (!backgroundOwnsLease) {
      await conversationStore.release(conversationId, conversationLeaseOwner, lease.fenceToken);
    }
  }
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
  authoritativeRead = false,
  allowGenericTestResolver = false,
): Promise<void> {
  let heartbeat: ReturnType<typeof startConversationLeaseHeartbeat> | null = null;
  try {
    heartbeat = conversationId && conversationLeaseOwner && conversationFenceToken
      ? startConversationLeaseHeartbeat(conversationId, conversationLeaseOwner, conversationFenceToken)
      : null;
    if (heartbeat) await heartbeat.assertOwned();
    const genericTestResolver = allowGenericTestResolver ? runnerForTests : null;
    const readRunner = readRunnerForTests ?? genericTestResolver ?? runLocalPythonAgent;
    let outcome: WorkbenchOutcome;
    let resultPersistenceRequired = Boolean(
      conversationId && turnId && expectedSessionVersion !== undefined && !authoritativeRead,
    );
    if (authoritativeRead && conversationId && turnId && expectedSessionVersion !== undefined) {
      const resolution = await readRunner({
        mode: "resolve-read",
        query,
        gatewayUrl: gatewayUrl(),
        intentMode: intentMode(),
        context,
        principal,
        turnId,
      });
      if (heartbeat) await heartbeat.assertOwned();
      const current = await getSession(conversationId, principalId);
      if (current.stateVersion !== expectedSessionVersion) {
        throw new ConversationProtocolError(
          "CONTEXT_VERSION_CONFLICT",
          `Conversation state changed from version ${expectedSessionVersion} to ${current.stateVersion}`,
        );
      }

      const readState = resolution.conversationReadState;
      const decisionType = textValue(resolution.decision?.decisionType)
        ?? textValue(resolution.matchDecision?.decisionType);
      const resolutionKind = textValue(resolution.resolutionReport?.resolutionKind);
      const isNonReadResolution = resolutionKind === "non_read"
        && readState !== null && readState !== undefined
        && resolution.turnId === turnId
        && resolution.stateVersion === readState.stateVersion
        && typeof decisionType === "string";
      const isReadResolution = !isNonReadResolution
        && resolution.status !== "resolved_selection"
        && readState !== null && readState !== undefined
        && resolution.turnId === turnId
        && resolution.stateVersion === readState.stateVersion
        && typeof decisionType === "string";
      if (isReadResolution) {
        validateReadResolution(
          resolution,
          current,
          turnId,
          principalId,
          expectedSessionVersion + 1,
          decisionType,
        );
        const nextHistory = [...current.history, { role: "user" as const, content: query }];
        if (decisionType !== "SELECT" && resolution.responseText) {
          nextHistory.push({ role: "assistant", content: resolution.responseText });
        }
        const nextSession: SessionStateV2 = {
          ...current,
          stateVersion: readState.stateVersion,
          activeFrame: readState.activeFrame,
          recentFrames: readState.recentFrames,
          pendingInteraction: readState.pendingInteraction,
          history: nextHistory,
          lastAppliedTurnId: turnId,
          lastRunId: runId,
        };
        await saveConversationState(
          conversationId,
          current.stateVersion,
          nextSession,
          conversationLeaseOwner!,
          conversationFenceToken!,
        );
        expectedSessionVersion = nextSession.stateVersion;

        if (decisionType === "SELECT") {
          if (!resolution.callPlan || !resolution.readExecutionBinding) {
            throw new ConversationProtocolError(
              "CONTEXT_VERSION_CONFLICT",
              "SELECT resolution is missing its immutable READ continuation binding",
            );
          }
          await assertContinuationSession(
            conversationId,
            principalId,
            turnId,
            runId,
            nextSession,
            heartbeat!,
          );
          const continued = await readRunner({
            mode: "continue-read",
            query,
            gatewayUrl: gatewayUrl(),
            intentMode: intentMode(),
            principal,
            turnId,
            callPlan: resolution.callPlan,
            readExecutionBinding: resolution.readExecutionBinding,
            persistedReadState: {
              activeFrame: nextSession.activeFrame,
              recentFrames: nextSession.recentFrames,
              pendingInteraction: nextSession.pendingInteraction,
              stateVersion: nextSession.stateVersion,
            },
            signal: heartbeat!.signal,
          });
          outcome = {
            ...continued,
            matchDecision: resolution.matchDecision,
            decision: resolution.decision,
            turnId: resolution.turnId,
            frameId: resolution.frameId,
            stateVersion: resolution.stateVersion,
            registrySnapshotId: resolution.registrySnapshotId,
            conversationReadState: resolution.conversationReadState,
            resolutionReport: resolution.resolutionReport,
          };
          resultPersistenceRequired = true;
        } else {
          outcome = resolution;
        }
      } else if (resolution.status === "resolved_selection") {
        if (!resolution.callPlan || !resolution.selectionExecutionBinding) {
          throw new ConversationProtocolError(
            "CONTEXT_VERSION_CONFLICT",
            "Resolved non-READ selection is missing its immutable continuation binding",
          );
        }
        validateNonReadResolution(
          resolution,
          current,
          turnId,
          principalId,
          expectedSessionVersion + 1,
        );
        const nextReadState = resolution.conversationReadState!;
        const binding = resolution.selectionExecutionBinding;
        if (
          nextReadState.pendingInteraction !== null
          || binding.turnId !== turnId
          || binding.stateVersion !== expectedSessionVersion + 1
          || binding.principalId !== principalId
          || binding.registrySnapshotId !== resolution.registrySnapshotId
          || binding.capabilityId !== resolution.callPlan.capabilityId
          || resolution.callPlan.kind !== "Action"
          || resolution.callPlan.requiresApproval !== true
          || sha256Hex(canonicalJson(resolution.callPlan)) !== binding.callPlanHash
        ) {
          throw new ConversationProtocolError(
            "CONTEXT_VERSION_CONFLICT",
            "Resolved non-READ selection binding is incomplete or mismatched",
          );
        }
        const nextSession: SessionStateV2 = {
          ...current,
          stateVersion: nextReadState.stateVersion,
          activeFrame: nextReadState.activeFrame,
          recentFrames: nextReadState.recentFrames,
          pendingInteraction: nextReadState.pendingInteraction,
          history: [...current.history, { role: "user", content: query }],
          lastAppliedTurnId: turnId,
          lastRunId: runId,
        };
        await saveConversationState(
          conversationId,
          current.stateVersion,
          nextSession,
          conversationLeaseOwner!,
          conversationFenceToken!,
        );
        expectedSessionVersion = nextSession.stateVersion;
        await assertContinuationSession(
          conversationId,
          principalId,
          turnId,
          runId,
          nextSession,
          heartbeat!,
        );
        outcome = await readRunner({
          mode: "continue-selection",
          query,
          gatewayUrl: gatewayUrl(),
          intentMode: intentMode(),
          principal,
          turnId,
          callPlan: resolution.callPlan,
          selectionExecutionBinding: binding,
        });
        resultPersistenceRequired = true;
      } else if (isNonReadResolution) {
        validateNonReadResolution(
          resolution,
          current,
          turnId,
          principalId,
          expectedSessionVersion + 1,
        );
        const nextHistory = [...current.history, { role: "user" as const, content: query }];
        if (resolution.responseText) {
          nextHistory.push({ role: "assistant", content: resolution.responseText });
        }
        const nextSession: SessionStateV2 = {
          ...current,
          stateVersion: readState!.stateVersion,
          activeFrame: readState!.activeFrame,
          recentFrames: readState!.recentFrames,
          pendingInteraction: readState!.pendingInteraction,
          history: nextHistory,
          lastAppliedTurnId: turnId,
          lastRunId: runId,
        };
        await saveConversationState(
          conversationId,
          current.stateVersion,
          nextSession,
          conversationLeaseOwner!,
          conversationFenceToken!,
        );
        expectedSessionVersion = nextSession.stateVersion;
        outcome = resolution;
      } else {
        const nextSession: SessionStateV2 = {
          ...current,
          stateVersion: current.stateVersion + 1,
          history: [...current.history, { role: "user", content: query }],
          lastAppliedTurnId: turnId,
          lastRunId: runId,
        };
        await saveConversationState(
          conversationId,
          current.stateVersion,
          nextSession,
          conversationLeaseOwner!,
          conversationFenceToken!,
        );
        expectedSessionVersion = nextSession.stateVersion;
        outcome = resolution;
        resultPersistenceRequired = true;
      }
    } else {
      throw new ConversationProtocolError(
        "CONTEXT_VERSION_CONFLICT",
        "Conversation execution requires authoritative resolution",
      );
    }
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

    if (
      resultPersistenceRequired
      && conversationId
      && turnId
      && expectedSessionVersion !== undefined
    ) {
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
      if (
        outcome.status === "awaiting_batch_confirm"
        && conversationId
        && turnId
        && outcome.conversationReadState?.pendingInteraction?.kind === "BATCH_CONFIRMATION"
      ) {
        const pending = outcome.conversationReadState.pendingInteraction;
        const batchAuthority = outcome.readExecutionBinding;
        if (!batchAuthority || !outcome.callPlan) {
          throw new ConversationProtocolError(
            "CONTEXT_VERSION_CONFLICT",
            "Batch resolution is missing current execution authority",
          );
        }
        outcome = {
          ...outcome,
          batchConversationBinding: {
            conversationId,
            turnId,
            frameId: pending.frameId,
            stateVersion: pending.stateVersion,
            registrySnapshotId: pending.registrySnapshotId,
            principalId,
            capabilityVersion: batchAuthority.capabilityVersion,
            executorBindingId: batchAuthority.executorBindingId,
            callPlanHash: batchAuthority.callPlanHash,
            batchRef: pending.batchRef,
          },
        };
      }
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

function validateNonReadResolution(
  outcome: WorkbenchOutcome,
  current: SessionStateV2,
  turnId: string,
  principalId: string,
  expectedVersion: number,
): void {
  const state = outcome.conversationReadState;
  const pending = state?.pendingInteraction;
  const expectedFrameId = state?.activeFrame?.frameId ?? outcome.frameId;
  if (
    outcome.resolutionReport?.resolutionKind !== "non_read"
    || !state
    || state.stateVersion !== expectedVersion
    || outcome.stateVersion !== expectedVersion
    || outcome.turnId !== turnId
    || current.principalId !== principalId
    || canonicalJson(state.activeFrame) !== canonicalJson(current.activeFrame)
    || canonicalJson(state.recentFrames) !== canonicalJson(current.recentFrames)
    || (state.activeFrame?.frameId ?? pending?.frameId ?? null) !== (outcome.frameId ?? null)
    || (pending != null && (
      pending.frameId !== expectedFrameId
      || pending.stateVersion !== expectedVersion
      || pending.registrySnapshotId !== outcome.registrySnapshotId
    ))
  ) {
    throw new ConversationProtocolError(
      "CONTEXT_VERSION_CONFLICT",
      "Resolved non-READ state does not match the claimed conversation turn",
    );
  }
}

function validateReadResolution(
  outcome: WorkbenchOutcome,
  current: SessionStateV2,
  turnId: string,
  principalId: string,
  expectedVersion: number,
  decisionType: string,
): void {
  const state = outcome.conversationReadState!;
  const frame = state.activeFrame;
  if (
    state.stateVersion !== expectedVersion
    || outcome.stateVersion !== expectedVersion
    || outcome.turnId !== turnId
    || current.principalId !== principalId
  ) {
    throw new ConversationProtocolError(
      "CONTEXT_VERSION_CONFLICT",
      "Resolved READ state does not match the claimed conversation turn",
    );
  }
  if (frame && (
    frame.frameId !== outcome.frameId
    || frame.updatedTurnId !== turnId
    || frame.registrySnapshotId !== outcome.registrySnapshotId
  )) {
    throw new ConversationProtocolError(
      "CONTEXT_VERSION_CONFLICT",
      "Resolved READ frame binding does not match the turn",
    );
  }
  const pending = state.pendingInteraction;
  if (pending && (
    pending.frameId !== outcome.frameId
    || pending.stateVersion !== expectedVersion
    || pending.registrySnapshotId !== outcome.registrySnapshotId
  )) {
    throw new ConversationProtocolError(
      "CONTEXT_VERSION_CONFLICT",
      "Resolved READ pending interaction is not bound to the next state",
    );
  }
  if (decisionType !== "SELECT") return;

  const binding = outcome.readExecutionBinding;
  const capabilityId = textValue(outcome.callPlan?.capabilityId);
  if (
    !frame
    || frame.status !== "READY"
    || pending !== null
    || !binding
    || binding.turnId !== turnId
    || binding.frameId !== frame.frameId
    || binding.stateVersion !== expectedVersion
    || binding.registrySnapshotId !== frame.registrySnapshotId
    || binding.principalId !== principalId
    || binding.capabilityVersion !== frame.capabilityVersion
    || !binding.executorBindingId
    || binding.readState.stateVersion !== state.stateVersion
    || binding.readState.activeFrame?.frameId !== frame.frameId
    || canonicalJson(binding.readState) !== canonicalJson(state)
    || capabilityId !== frame.capabilityId
    || outcome.callPlan?.kind !== "Function"
    || outcome.callPlan?.requiresApproval !== false
    || sha256Hex(canonicalJson(outcome.callPlan)) !== binding.callPlanHash
  ) {
    throw new ConversationProtocolError(
      "CONTEXT_VERSION_CONFLICT",
      "Resolved READ continuation binding is incomplete or mismatched",
    );
  }
}

async function saveConversationState(
  conversationId: string,
  expectedVersion: number,
  next: SessionStateV2,
  leaseOwner: string,
  fenceToken: string,
): Promise<void> {
  const saved = await conversationStore.compareAndSwap(
    conversationId,
    expectedVersion,
    next,
    { workerId: leaseOwner, fenceToken },
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
      `Conversation state changed from version ${expectedVersion} to ${saved.actualVersion}`,
    );
  }
}

function startConversationLeaseHeartbeat(
  conversationId: string,
  owner: string,
  fenceToken: string,
): { assertOwned: () => Promise<void>; signal: AbortSignal; stop: () => void } {
  let stopped = false;
  let lost: Error | null = null;
  let renewal: Promise<void> | null = null;
  const abortController = new AbortController();

  const markLost = (error: Error) => {
    if (lost) return;
    lost = error;
    abortController.abort(error);
  };

  const renew = async (): Promise<void> => {
    if (stopped || lost) return;
    const outcome = await conversationStore.renew(
      conversationId,
      owner,
      fenceToken,
      CONVERSATION_LEASE_TTL_MS,
    );
    if (outcome.status === "lost") {
      markLost(new ConversationProtocolError(
        "CONVERSATION_BUSY",
        `Conversation lease ownership was lost${outcome.holder ? ` to ${outcome.holder}` : ""}`,
      ));
    }
  };
  const scheduleRenewal = () => {
    if (renewal || stopped || lost) return;
    renewal = renew()
      .catch((error: unknown) => {
        markLost(error instanceof Error ? error : new Error(String(error)));
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
    signal: abortController.signal,
    stop: () => {
      stopped = true;
      clearInterval(timer);
    },
  };
}

async function assertContinuationSession(
  conversationId: string,
  principalId: string,
  turnId: string,
  runId: string,
  expected: SessionStateV2,
  heartbeat: { assertOwned: () => Promise<void> },
): Promise<void> {
  await heartbeat.assertOwned();
  const current = await getSession(conversationId, principalId);
  if (
    current.principalId !== principalId
    || current.stateVersion !== expected.stateVersion
    || current.lastAppliedTurnId !== turnId
    || current.lastRunId !== runId
    || canonicalJson(current.activeFrame) !== canonicalJson(expected.activeFrame)
    || canonicalJson(current.pendingInteraction) !== canonicalJson(expected.pendingInteraction)
  ) {
    throw new ConversationProtocolError(
      "CONTEXT_VERSION_CONFLICT",
      "Conversation binding changed immediately before continuation",
    );
  }
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
      mode: "continue-action",
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
  const binding = record.pendingOutcome.batchConversationBinding;
  if (!callPlan || !combinations || !binding) {
    throw new Error("Agent run batch context is incomplete");
  }

  const conversationLeaseOwner = `${workerId}:batch:${crypto.randomUUID()}`;
  const conversationLease = await conversationStore.claim(
    binding.conversationId,
    conversationLeaseOwner,
    CONVERSATION_LEASE_TTL_MS,
  );
  if (conversationLease.status === "rejected") {
    throw new ConversationProtocolError(
      "CONVERSATION_BUSY",
      `Conversation is held by another worker (${conversationLease.holder})`,
    );
  }

  let backgroundOwnsConversationLease = false;
  let runLeaseClaimed = false;
  try {
    const session = await conversationStore.load(
      binding.conversationId,
      principal.principalId,
    );
    const pending = session?.pendingInteraction;
    const activeFrame = session?.activeFrame;
    const expectedBatchRef = `sha256:${sha256Hex(canonicalJson({ callPlan, combinations }))}`;
    if (
      !session
      || binding.principalId !== principal.principalId
      || session.principalId !== principal.principalId
      || session.stateVersion !== binding.stateVersion
      || session.lastAppliedTurnId !== binding.turnId
      || session.lastRunId !== runId
      || pending?.kind !== "BATCH_CONFIRMATION"
      || pending.frameId !== binding.frameId
      || pending.stateVersion !== binding.stateVersion
      || pending.registrySnapshotId !== binding.registrySnapshotId
      || activeFrame?.frameId !== binding.frameId
    ) {
      throw new ConversationProtocolError(
        "CONTEXT_VERSION_CONFLICT",
        "Batch confirmation binding is invalid, expired, or stale",
      );
    }
    const executionAuthorityIsInvalid = (
      pending.batchRef !== binding.batchRef
      || pending.batchRef !== expectedBatchRef
      || Date.parse(pending.expiresAt) <= Date.now()
      || activeFrame.status !== "READY"
      || activeFrame.registrySnapshotId !== binding.registrySnapshotId
      || activeFrame.capabilityVersion !== binding.capabilityVersion
      || activeFrame.capabilityId !== callPlan.capabilityId
      || !binding.executorBindingId
      || sha256Hex(canonicalJson(callPlan)) !== binding.callPlanHash
      || callPlan.kind !== "Function"
      || callPlan.requiresApproval !== false
    );
    if (executionAuthorityIsInvalid) {
      const invalidLease = await runStore.claim(runId, workerId, 60_000);
      if (invalidLease.status === "rejected") {
        throw new Error(`Agent run is held by another worker (${invalidLease.holder}); takeover rejected (fail-closed).`);
      }
      runLeaseClaimed = true;
      await saveConversationState(
        binding.conversationId,
        session.stateVersion,
        { ...session, stateVersion: session.stateVersion + 1, pendingInteraction: null },
        conversationLeaseOwner,
        conversationLease.fenceToken,
      );
      await runStore.appendDecision(runId, "reject");
      throw new ConversationProtocolError(
        "CONTEXT_VERSION_CONFLICT",
        "Batch confirmation binding is invalid, expired, or stale",
      );
    }

    const lease = await runStore.claim(runId, workerId, 60_000);
    if (lease.status === "rejected") {
      throw new Error(`Agent run is held by another worker (${lease.holder}); takeover rejected (fail-closed).`);
    }
    runLeaseClaimed = true;
    const consumedSession: SessionStateV2 = {
      ...session,
      stateVersion: session.stateVersion + 1,
      pendingInteraction: null,
    };
    await saveConversationState(
      binding.conversationId,
      session.stateVersion,
      consumedSession,
      conversationLeaseOwner,
      conversationLease.fenceToken,
    );
    await runStore.appendDecision(runId, "approve");
    backgroundOwnsConversationLease = true;
    void executeBatchInBackground(
      runId,
      record,
      callPlan,
      combinations,
      idemKey,
      binding.conversationId,
      conversationLeaseOwner,
      conversationLease.fenceToken,
      principal,
      binding.turnId,
      consumedSession,
      {
        turnId: binding.turnId,
        frameId: binding.frameId,
        stateVersion: consumedSession.stateVersion,
        registrySnapshotId: binding.registrySnapshotId,
        principalId: binding.principalId,
        capabilityVersion: binding.capabilityVersion,
        executorBindingId: binding.executorBindingId,
        callPlanHash: binding.callPlanHash,
        readState: {
          activeFrame: consumedSession.activeFrame,
          recentFrames: consumedSession.recentFrames,
          pendingInteraction: consumedSession.pendingInteraction,
          stateVersion: consumedSession.stateVersion,
        },
      },
    );
  } catch (error) {
    if (runLeaseClaimed) await runStore.release(runId, workerId);
    throw error;
  } finally {
    if (!backgroundOwnsConversationLease) {
      await conversationStore.release(
        binding.conversationId,
        conversationLeaseOwner,
        conversationLease.fenceToken,
      );
    }
  }
}

async function executeBatchInBackground(
  runId: string,
  record: AgentRunRecord,
  callPlan: Record<string, unknown>,
  combinations: Record<string, string>[],
  idemKey: string,
  conversationId: string,
  conversationLeaseOwner: string,
  conversationFenceToken: string,
  principal: TrustedPrincipal,
  turnId: string,
  expectedSession: SessionStateV2,
  readExecutionBinding: ReadExecutionBinding,
): Promise<void> {
  const heartbeat = startConversationLeaseHeartbeat(
    conversationId,
    conversationLeaseOwner,
    conversationFenceToken,
  );
  try {
    await assertContinuationSession(
      conversationId,
      principal.principalId,
      turnId,
      runId,
      expectedSession,
      heartbeat,
    );
    const runner = runnerForTests ?? runLocalPythonAgent;
    const outcome = await runner({
      mode: "continue-batch",
      query: record.query,
      gatewayUrl: gatewayUrl(),
      intentMode: intentMode(),
      principal,
      continuation: {
        type: "batch",
        callPlan,
        combinations,
        readExecutionBinding,
        persistedReadState: readExecutionBinding.readState,
      },
      signal: heartbeat.signal,
    });
    await heartbeat.assertOwned();
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
  } finally {
    heartbeat.stop();
    await conversationStore.release(
      conversationId,
      conversationLeaseOwner,
      conversationFenceToken,
    );
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

  if (input.mode === "resolve-read") {
    if (!input.context || !input.turnId) {
      throw new Error("Authoritative READ resolution requires context and turnId.");
    }
    args = [
      "-m",
      "sap_nexus_agent.cli",
      input.query,
      "--resolve-read-turn",
      "--turn-id",
      input.turnId,
      "--gateway-url",
      input.gatewayUrl,
      "--intent-mode",
      input.intentMode,
      "--json",
    ];
    stdinPayload = JSON.stringify(input.context);
  } else if (input.mode === "preflight-batch") {
    if (input.continuation?.type !== "batch") {
      throw new Error("Batch authority preflight requires a server-owned batch binding.");
    }
    args = [
      "-m",
      "sap_nexus_agent.cli",
      "--preflight-batch",
      "--json",
    ];
    stdinPayload = JSON.stringify(input.continuation);
  } else if (input.mode === "continue-read") {
    if (!input.callPlan || !input.readExecutionBinding || !input.persistedReadState) {
      throw new Error("Authoritative READ continuation requires a server-owned binding.");
    }
    args = [
      "-m",
      "sap_nexus_agent.cli",
      "--continue-read",
      "--gateway-url",
      input.gatewayUrl,
      "--json",
    ];
    stdinPayload = JSON.stringify({
      callPlan: input.callPlan,
      binding: input.readExecutionBinding,
      persistedReadState: input.persistedReadState,
    });
  } else if (input.mode === "continue-selection") {
    if (!input.callPlan || !input.selectionExecutionBinding) {
      throw new Error("Selection continuation requires a server-owned binding.");
    }
    args = [
      "-m",
      "sap_nexus_agent.cli",
      "--continue-selection",
      "--gateway-url",
      input.gatewayUrl,
      "--json",
    ];
    stdinPayload = JSON.stringify({
      callPlan: input.callPlan,
      binding: input.selectionExecutionBinding,
    });
  } else {
    if (!input.continuation) {
      throw new Error(`${input.mode} requires a server-owned continuation payload.`);
    }
    const isBatch = input.mode === "continue-batch";
    if (isBatch !== (input.continuation.type === "batch")) {
      throw new Error(`${input.mode} continuation payload type is invalid.`);
    }
    args = [
      "-m",
      "sap_nexus_agent.cli",
      isBatch ? "--continue-batch" : "--continue-action",
      "--gateway-url",
      input.gatewayUrl,
      "--json"
    ];
    stdinPayload = JSON.stringify(input.continuation);
  }
  const env = {
    ...process.env,
    PYTHONPATH: [path.join(repoRoot, "agent"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    ...(input.principal ? { SAP_NEXUS_PRINCIPAL: JSON.stringify(input.principal) } : {})
  };

  const { stdout } = await spawnAndCapture(
    python,
    args,
    repoRoot,
    env,
    stdinPayload,
    input.signal,
  );
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
  stdinPayload?: string,
  signal?: AbortSignal,
): Promise<{ stdout: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env });
    let stdout = "";
    let settled = false;
    const cleanup = () => signal?.removeEventListener("abort", abort);
    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };
    const abort = () => {
      child.kill();
      fail(signal?.reason instanceof Error ? signal.reason : new Error("Agent runner aborted."));
    };
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", () => {
      // stderr may contain environment-specific details; never forward it to the UI.
    });
    if (stdinPayload !== undefined) {
      child.stdin.end(stdinPayload);
    }
    child.on("error", () => fail(new Error("Agent runner process could not be started.")));
    child.on("close", () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve({ stdout });
    });
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
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
