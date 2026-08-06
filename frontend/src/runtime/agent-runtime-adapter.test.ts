import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  confirmAgentRunBatch,
  createAgentRun,
  decideAgentRunApproval,
  getAgentRunEvents,
  resetAgentRunsForTests,
  resetAgentSessionsForTests,
  setAgentRunnerForTests,
  setReadAgentRunnerForTests,
  setDurableStoresForTests
} from "./agent-runtime-adapter";
import { JsonlConversationStore } from "./durable/jsonl-conversation-store";
import { JsonlRunStore } from "./durable/jsonl-run-store";
import { canonicalJson, sha256Hex } from "./durable/canonical-json";
import type { ConversationReadState, WorkbenchOutcome } from "./durable/types";
import { PLACEHOLDER_PRINCIPAL } from "./principal/types";
import type { TrustedPrincipal } from "./principal/types";
import type { AgentRunEvent } from "./run-event-schema";

function awaitingOutcome(runId: string): WorkbenchOutcome {
  return {
    status: "awaiting_approval",
    callPlan: { capabilityId: "cap-1", kind: "Action", agentTraceId: "t" },
    validationResult: { success: true, capabilityId: "cap-1", traceId: "g" },
    approvalRecord: { id: "apr-1", status: "pending" },
    responseText: "待审批"
  };
}

function resolvedReadOutcome(turnId: string, stateVersion = 1): WorkbenchOutcome {
  const readState = {
    activeFrame: {
      frameId: "frame-read-1",
      capabilityId: "MM.Inventory.GetAvailability",
      slots: {
        material: {
          name: "material", value: "DEMOA2", candidates: ["DEMOA2"],
          state: "RESOLVED" as const, provenance: "EXPLICIT" as const,
          sourceTurnId: turnId, sourceSpan: null, issues: [],
        },
        plant: {
          name: "plant", value: "1000", candidates: ["1000"],
          state: "RESOLVED" as const, provenance: "EXPLICIT" as const,
          sourceTurnId: turnId, sourceSpan: null, issues: [],
        },
      },
      status: "READY" as const,
      createdTurnId: turnId,
      updatedTurnId: turnId,
      registrySnapshotId: "snapshot-read-1",
      capabilityVersion: "1",
    },
    recentFrames: [],
    pendingInteraction: null,
    stateVersion,
  };
  const callPlan = {
    agentTraceId: "agent-read-1",
    capabilityId: "MM.Inventory.GetAvailability",
    kind: "Function",
    parameters: { material: "DEMOA2", plant: "1000", unit: "EA" },
    validationPolicy: "validate_before_execute",
    createdBy: "agent",
    requiresApproval: false,
  };
  return {
    status: "resolved_read",
    callPlan,
    matchDecision: { decisionType: "SELECT", capabilityId: callPlan.capabilityId },
    decision: { decisionType: "SELECT", capabilityId: callPlan.capabilityId },
    conversationReadState: readState,
    resolutionReport: { frameStatus: "READY" },
    turnId,
    frameId: "frame-read-1",
    stateVersion,
    registrySnapshotId: "snapshot-read-1",
    readExecutionBinding: {
      turnId,
      frameId: "frame-read-1",
      stateVersion,
      registrySnapshotId: "snapshot-read-1",
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      capabilityVersion: "1",
      executorBindingId: "sap.mm.inventory.md04-stock-req-list",
      callPlanHash: sha256Hex(canonicalJson(callPlan)),
      readState,
    },
    responseText: "ready",
  };
}

function clarifyReadOutcome(turnId: string, stateVersion = 1): WorkbenchOutcome {
  const resolved = resolvedReadOutcome(turnId, stateVersion);
  const frame = resolved.conversationReadState!.activeFrame!;
  frame.status = "COLLECTING";
  frame.slots.material = {
    ...frame.slots.material,
    value: null,
    candidates: [],
    state: "CLEARED",
  };
  resolved.status = "clarification";
  resolved.callPlan = null;
  resolved.matchDecision = {
    decisionType: "CLARIFY",
    capabilityId: "MM.Inventory.GetAvailability",
    missingParameters: ["material"],
  };
  resolved.decision = resolved.matchDecision;
  resolved.readExecutionBinding = null;
  resolved.conversationReadState!.pendingInteraction = {
    kind: "SLOT_CLARIFICATION",
    frameId: "frame-read-1",
    expectedFields: ["material"],
    stateVersion,
    registrySnapshotId: "snapshot-read-1",
    expiresAt: "2099-01-01T00:00:00Z",
  };
  return resolved;
}

function batchReadOutcome(turnId: string, stateVersion = 1): WorkbenchOutcome {
  const resolved = resolvedReadOutcome(turnId, stateVersion);
  const combinations = [
    { material: "DEMOA2", plant: "1000", unit: "EA" },
    { material: "DEMOA2", plant: "5100", unit: "EA" },
  ];
  const batchRef = `sha256:${sha256Hex(canonicalJson({
    callPlan: resolved.callPlan,
    combinations,
  }))}`;
  resolved.status = "awaiting_batch_confirm";
  resolved.combinations = combinations;
  resolved.matchDecision = {
    decisionType: "CLARIFY",
    capabilityId: "MM.Inventory.GetAvailability",
  };
  resolved.decision = resolved.matchDecision;
  resolved.readExecutionBinding = null;
  resolved.conversationReadState!.pendingInteraction = {
    kind: "BATCH_CONFIRMATION",
    frameId: "frame-read-1",
    batchRef,
    stateVersion,
    registrySnapshotId: "snapshot-read-1",
    expiresAt: "2099-01-01T00:00:00Z",
  };
  resolved.readExecutionBinding = {
    turnId,
    frameId: "frame-read-1",
    stateVersion,
    registrySnapshotId: "snapshot-read-1",
    principalId: PLACEHOLDER_PRINCIPAL.principalId,
    capabilityVersion: "1",
    executorBindingId: "sap.mm.inventory.md04-stock-req-list",
    callPlanHash: sha256Hex(canonicalJson(resolved.callPlan)),
    readState: resolved.conversationReadState!,
  };
  return resolved;
}

function resolvedSelectionOutcome(
  turnId: string,
  stateVersion = 1,
  activeFrame: ConversationReadState["activeFrame"] = null,
): WorkbenchOutcome {
  const callPlan = {
    agentTraceId: "agent-write-1",
    capabilityId: "MM.PR.CreateDraft",
    kind: "Action",
    parameters: {
      material: "DEMOA2", plant: "1000", quantity: "10", unit: "EA",
      delivery_date: "2026-08-10", purchasing_group: "001",
    },
    validationPolicy: "validate_before_execute",
    createdBy: "agent",
    requiresApproval: true,
  };
  return {
    status: "resolved_selection",
    callPlan,
    matchDecision: { decisionType: "SELECT", capabilityId: callPlan.capabilityId },
    decision: { decisionType: "SELECT", capabilityId: callPlan.capabilityId },
    conversationReadState: {
      activeFrame,
      recentFrames: [],
      pendingInteraction: null,
      stateVersion,
    },
    resolutionReport: { resolutionKind: "non_read" },
    turnId,
    frameId: activeFrame?.frameId ?? null,
    stateVersion,
    registrySnapshotId: "snapshot-write-1",
    selectionExecutionBinding: {
      turnId,
      stateVersion,
      registrySnapshotId: "snapshot-write-1",
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      capabilityId: callPlan.capabilityId,
      capabilityVersion: "1",
      executorBindingId: "sap.mm.pr.create-draft",
      callPlanHash: sha256Hex(canonicalJson(callPlan)),
    },
  };
}

function setInitialSelectionForTests(
  continuation: (input: any) => Promise<WorkbenchOutcome> | WorkbenchOutcome,
): void {
  setReadAgentRunnerForTests(async (input) => {
    if (input.mode === "resolve-read") return resolvedSelectionOutcome(input.turnId!);
    if (input.mode === "continue-selection") return continuation(input);
    throw new Error(`unexpected selection runner mode ${input.mode}`);
  });
}

function setInitialReadForTests(
  continuation: (input: any) => Promise<WorkbenchOutcome> | WorkbenchOutcome,
): void {
  setReadAgentRunnerForTests(async (input) => {
    if (input.mode === "resolve-read") return resolvedReadOutcome(input.turnId!);
    if (input.mode === "continue-read") return continuation(input);
    throw new Error(`unexpected READ runner mode ${input.mode}`);
  });
}

async function waitForRunSettled(runId: string, timeoutMs = 5000, minEventCount = 0): Promise<AgentRunEvent[]> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    if (events.length > minEventCount) {
      const last = events[events.length - 1];
      if (last.type === "run_completed" || last.type === "run_failed" ||
          last.state === "awaiting_approval" || last.state === "awaiting_batch_confirm" ||
          last.state === "rejected") {
        return events;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`Run ${runId} did not settle within ${timeoutMs}ms`);
}

describe("agent-runtime-adapter durable integration", () => {
  let dir: string;
  let runStore: JsonlRunStore;
  let convStore: JsonlConversationStore;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "adapter-"));
    runStore = new JsonlRunStore(dir);
    convStore = new JsonlConversationStore(dir);
    setDurableStoresForTests(runStore, convStore);
    setInitialSelectionForTests(async () => awaitingOutcome("run-1"));
  });
  afterEach(() => {
    setAgentRunnerForTests(null);
    setReadAgentRunnerForTests(null);
    setDurableStoresForTests(
      new JsonlRunStore(mkdtempSync(path.join(tmpdir(), "teardown-"))),
      new JsonlConversationStore(mkdtempSync(path.join(tmpdir(), "teardown-")))
    );
    rmSync(dir, { recursive: true, force: true });
  });

  it("createAgentRun persists events to durable store", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(events.length).toBeGreaterThan(0);
    expect(events[0].type).toBe("run_started");
  });

  it("preserves a supplied turnId and generates one only when absent", async () => {
    setInitialReadForTests(async () => ({ status: "success", responseText: "ok" } as WorkbenchOutcome));
    const supplied = await createAgentRun({
      query: "查询库存",
      conversationId: "c-turn-supplied",
      turnId: "client-turn-1",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    const generated = await createAgentRun({
      query: "查询库存",
      conversationId: "c-turn-generated",
      principal: PLACEHOLDER_PRINCIPAL,
    });

    await Promise.all([waitForRunSettled(supplied.runId), waitForRunSettled(generated.runId)]);

    expect(supplied.turnId).toBe("client-turn-1");
    expect(generated.turnId).toMatch(/^turn-/);
    expect(generated.turnId).not.toBe(supplied.turnId);
  });

  it("persists resolved Frame v2 before continuing a SELECT", async () => {
    const phases: string[] = [];
    setReadAgentRunnerForTests(async (input) => {
      phases.push(input.mode);
      if (input.mode === "resolve-read") {
        return resolvedReadOutcome(input.turnId!);
      }
      if (input.mode === "continue-read") {
        const persisted = await convStore.load("c-read-order", PLACEHOLDER_PRINCIPAL.principalId);
        expect(persisted?.stateVersion).toBe(1);
        expect(persisted?.activeFrame?.status).toBe("READY");
        expect(persisted?.lastAppliedTurnId).toBe("turn-read-order");
        return { status: "success", responseText: "库存 7 EA" };
      }
      throw new Error(`unexpected runner mode ${input.mode}`);
    });

    const { runId } = await createAgentRun({
      query: "查库存",
      conversationId: "c-read-order",
      turnId: "turn-read-order",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);

    expect(phases).toEqual(["resolve-read", "continue-read"]);
  });

  it("generates an internal conversation id and still CASes before READ continuation", async () => {
    const phases: string[] = [];
    let oneShotQueries = 0;
    const cas = vi.spyOn(convStore, "compareAndSwap");
    setAgentRunnerForTests(async () => {
      oneShotQueries++;
      return { status: "success", responseText: "legacy" };
    });
    setReadAgentRunnerForTests(async (input) => {
      phases.push(input.mode);
      if (input.mode === "resolve-read") return resolvedReadOutcome(input.turnId!);
      if (input.mode === "continue-read") {
        expect(cas).toHaveBeenCalled();
        return { status: "success", responseText: "库存 7 EA" };
      }
      throw new Error(`unexpected runner mode ${input.mode}`);
    });

    const { runId } = await createAgentRun({
      query: "查库存",
      turnId: "turn-generated-conversation",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);

    expect(phases).toEqual(["resolve-read", "continue-read"]);
    expect(oneShotQueries).toBe(0);
  });

  it("persists bound READ pending interaction across restart without continuation", async () => {
    let continuationCalls = 0;
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "continue-read") continuationCalls++;
      return clarifyReadOutcome(input.turnId!);
    });
    const { runId } = await createAgentRun({
      query: "换个物料能查吗",
      conversationId: "c-read-pending",
      turnId: "turn-read-pending",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);

    const reopened = new JsonlConversationStore(dir);
    const session = await reopened.load("c-read-pending", PLACEHOLDER_PRINCIPAL.principalId);
    expect(session?.pendingInteraction).toEqual({
      kind: "SLOT_CLARIFICATION",
      frameId: "frame-read-1",
      expectedFields: ["material"],
      stateVersion: 1,
      registrySnapshotId: "snapshot-read-1",
      expiresAt: "2099-01-01T00:00:00Z",
    });
    expect(continuationCalls).toBe(0);
  });

  it("CAS conflict prevents READ continuation", async () => {
    let continuationCalls = 0;
    const conflictStore = {
      load: convStore.load.bind(convStore),
      claim: convStore.claim.bind(convStore),
      compareAndSwap: vi.fn(async () => ({ status: "conflict" as const, actualVersion: 9 })),
      renew: convStore.renew.bind(convStore),
      release: convStore.release.bind(convStore),
      lookupTurn: convStore.lookupTurn.bind(convStore),
      clear: convStore.clear.bind(convStore),
      clearAll: convStore.clearAll.bind(convStore),
    };
    setDurableStoresForTests(runStore, conflictStore);
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "continue-read") continuationCalls++;
      return resolvedReadOutcome(input.turnId!);
    });

    const { runId } = await createAgentRun({
      query: "查库存",
      conversationId: "c-read-conflict",
      turnId: "turn-read-conflict",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);

    expect(continuationCalls).toBe(0);
  });

  it("re-loads the current Session immediately before READ continuation", async () => {
    let continuationCalls = 0;
    let resolutionPersisted = false;
    const load = vi.fn(async (conversationId: string, principalId: string) => {
      const session = await convStore.load(conversationId, principalId);
      if (!resolutionPersisted || !session) return session;
      return { ...session, stateVersion: session.stateVersion + 1 };
    });
    const guardedStore = {
      load,
      claim: convStore.claim.bind(convStore),
      compareAndSwap: vi.fn(async (...args: Parameters<typeof convStore.compareAndSwap>) => {
        const result = await convStore.compareAndSwap(...args);
        if (result.status === "saved") resolutionPersisted = true;
        return result;
      }),
      renew: convStore.renew.bind(convStore),
      release: convStore.release.bind(convStore),
      lookupTurn: convStore.lookupTurn.bind(convStore),
      clear: convStore.clear.bind(convStore),
      clearAll: convStore.clearAll.bind(convStore),
    };
    setDurableStoresForTests(runStore, guardedStore);
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "resolve-read") return resolvedReadOutcome(input.turnId!);
      if (input.mode === "continue-read") continuationCalls++;
      return { status: "success", responseText: "unexpected" };
    });

    const { runId } = await createAgentRun({
      query: "查库存",
      conversationId: "c-read-stale-session",
      turnId: "turn-read-stale-session",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);

    expect(continuationCalls).toBe(0);
  });

  it("asserts the current fence immediately before READ continuation", async () => {
    let continuationCalls = 0;
    let renewCalls = 0;
    const fencedStore = {
      load: convStore.load.bind(convStore),
      claim: convStore.claim.bind(convStore),
      compareAndSwap: convStore.compareAndSwap.bind(convStore),
      renew: vi.fn(async (...args: Parameters<typeof convStore.renew>) => {
        renewCalls++;
        if (renewCalls === 3) return { status: "lost" as const, holder: "takeover" };
        return convStore.renew(...args);
      }),
      release: convStore.release.bind(convStore),
      lookupTurn: convStore.lookupTurn.bind(convStore),
      clear: convStore.clear.bind(convStore),
      clearAll: convStore.clearAll.bind(convStore),
    };
    setDurableStoresForTests(runStore, fencedStore);
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "resolve-read") return resolvedReadOutcome(input.turnId!);
      if (input.mode === "continue-read") continuationCalls++;
      return { status: "success", responseText: "unexpected" };
    });

    const { runId } = await createAgentRun({
      query: "查库存",
      conversationId: "c-read-stale-fence",
      turnId: "turn-read-stale-fence",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);

    expect(renewCalls).toBeGreaterThanOrEqual(3);
    expect(continuationCalls).toBe(0);
  });

  it("aborts an in-flight READ child when the conversation heartbeat loses its lease", async () => {
    const conversationId = "c-read-mid-flight-loss";
    let gatewayCalls = 0;
    let abortObserved = false;
    let releaseBlockedRunner: (() => void) | undefined;
    let markRunnerStarted: (() => void) | undefined;
    const runnerStarted = new Promise<void>((resolve) => { markRunnerStarted = resolve; });
    let renewCalls = 0;
    const losingStore = {
      load: convStore.load.bind(convStore),
      claim: convStore.claim.bind(convStore),
      compareAndSwap: convStore.compareAndSwap.bind(convStore),
      renew: vi.fn(async (...args: Parameters<typeof convStore.renew>) => {
        renewCalls++;
        if (renewCalls === 4) return { status: "lost" as const, holder: "takeover" };
        return convStore.renew(...args);
      }),
      release: convStore.release.bind(convStore),
      lookupTurn: convStore.lookupTurn.bind(convStore),
      clear: convStore.clear.bind(convStore),
      clearAll: convStore.clearAll.bind(convStore),
    };
    setDurableStoresForTests(runStore, losingStore);
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "resolve-read") return resolvedReadOutcome(input.turnId!);
      if (input.mode !== "continue-read") throw new Error(`unexpected mode ${input.mode}`);
      gatewayCalls++;
      markRunnerStarted?.();
      await new Promise<void>((resolve, reject) => {
        releaseBlockedRunner = resolve;
        input.signal?.addEventListener("abort", () => {
          abortObserved = true;
          reject(input.signal?.reason instanceof Error ? input.signal.reason : new Error("READ aborted"));
        }, { once: true });
      });
      gatewayCalls++;
      return { status: "success", responseText: "unexpected" };
    });

    vi.useFakeTimers();
    try {
      const { runId } = await createAgentRun({
        query: "查库存",
        conversationId,
        turnId: "turn-read-mid-flight-loss",
        principal: PLACEHOLDER_PRINCIPAL,
      });
      await vi.advanceTimersByTimeAsync(0);
      await runnerStarted;
      await vi.advanceTimersByTimeAsync(20_000);

      expect(abortObserved).toBe(true);
      expect(gatewayCalls).toBe(1);
      await vi.advanceTimersByTimeAsync(0);
      expect((await runStore.load(runId))?.events.at(-1)).toMatchObject({
        type: "run_failed",
        error: { errorType: "CONVERSATION_BUSY" },
      });
    } finally {
      releaseBlockedRunner?.();
      await vi.advanceTimersByTimeAsync(0);
      vi.useRealTimers();
    }
  });

  it("continues the first non-READ selection without rerunning query semantics", async () => {
    const modes: string[] = [];
    let oneShotQueries = 0;
    setAgentRunnerForTests(async () => {
      oneShotQueries++;
      return { status: "success" };
    });
    setReadAgentRunnerForTests(async (input) => {
      modes.push(input.mode);
      if (input.mode === "resolve-read") {
        return resolvedSelectionOutcome(input.turnId!);
      }
      if (input.mode === "continue-selection") {
        const persisted = await convStore.load(
          "c-write-selection",
          PLACEHOLDER_PRINCIPAL.principalId,
        );
        expect(persisted?.lastAppliedTurnId).toBe("turn-write-selection");
        return awaitingOutcome("run-write-selection");
      }
      throw new Error(`unexpected mode ${input.mode}`);
    });

    const { runId } = await createAgentRun({
      query: "创建采购申请",
      conversationId: "c-write-selection",
      turnId: "turn-write-selection",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);

    expect(modes).toEqual(["resolve-read", "continue-selection"]);
    expect(oneShotQueries).toBe(0);
  });

  it("routes a real-shaped non-READ selection with an existing READ frame to Action approval", async () => {
    const conversationId = "c-write-existing-read-frame";
    const existingFrame = resolvedReadOutcome("turn-existing-read").conversationReadState!.activeFrame!;
    await convStore.compareAndSwap(conversationId, 0, {
      schemaVersion: 2,
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      stateVersion: 1,
      activeFrame: existingFrame,
      recentFrames: [],
      pendingInteraction: null,
      history: [],
      lastAppliedTurnId: null,
      lastRunId: null,
    });
    const modes: string[] = [];
    setReadAgentRunnerForTests(async (input) => {
      modes.push(input.mode);
      if (input.mode === "resolve-read") {
        return resolvedSelectionOutcome(input.turnId!, 2, existingFrame);
      }
      if (input.mode === "continue-selection") return awaitingOutcome("run-existing-frame");
      throw new Error(`unexpected mode ${input.mode}`);
    });

    const { runId } = await createAgentRun({
      query: "创建采购申请",
      conversationId,
      turnId: "turn-write-existing-read-frame",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);

    expect(modes).toEqual(["resolve-read", "continue-selection"]);
    expect((await convStore.load(conversationId, PLACEHOLDER_PRINCIPAL.principalId))?.activeFrame)
      .toEqual(existingFrame);
    expect((await runStore.load(runId))?.pendingOutcome?.status).toBe("awaiting_approval");
  });

  it.each([
    ["CLARIFY", null],
    ["SHOW_OPTIONS", "CAPABILITY_CHOICE"],
    ["ESCALATE_TO_PLANNER", "PLANNER_CONFIRMATION"],
  ] as const)(
    "persists real-shaped non-READ %s without treating an existing READ frame as current",
    async (decisionType, pendingKind) => {
      const conversationId = `c-non-read-${decisionType.toLowerCase()}`;
      const turnId = `turn-non-read-${decisionType.toLowerCase()}`;
      const existingFrame = resolvedReadOutcome("turn-existing-read").conversationReadState!.activeFrame!;
      await convStore.compareAndSwap(conversationId, 0, {
        schemaVersion: 2,
        principalId: PLACEHOLDER_PRINCIPAL.principalId,
        stateVersion: 1,
        activeFrame: existingFrame,
        recentFrames: [],
        pendingInteraction: null,
        history: [],
        lastAppliedTurnId: null,
        lastRunId: null,
      });
      const pendingInteraction = pendingKind === "CAPABILITY_CHOICE" ? {
        kind: "CAPABILITY_CHOICE" as const,
        frameId: existingFrame.frameId,
        capabilityIds: ["MM.PR.CreateDraft"],
        stateVersion: 2,
        registrySnapshotId: "snapshot-write-1",
        expiresAt: "2099-01-01T00:00:00Z",
      } : pendingKind === "PLANNER_CONFIRMATION" ? {
        kind: "PLANNER_CONFIRMATION" as const,
        frameId: existingFrame.frameId,
        plannerRef: "sha256:planner-write-1",
        plannerGoals: [{
          capabilityId: "MM.PR.CreateDraft",
          parameters: { material: "DEMOA2" },
          missing: ["plant"],
        }],
        stateVersion: 2,
        registrySnapshotId: "snapshot-write-1",
        expiresAt: "2099-01-01T00:00:00Z",
      } : null;
      const outcome: WorkbenchOutcome = {
        status: decisionType === "CLARIFY" ? "clarification" : "match_decision",
        responseText: "non-read response",
        callPlan: null,
        matchDecision: { decisionType, capabilityId: "MM.PR.CreateDraft" },
        decision: { decisionType, capabilityId: "MM.PR.CreateDraft" },
        conversationReadState: {
          activeFrame: existingFrame,
          recentFrames: [],
          pendingInteraction,
          stateVersion: 2,
        },
        resolutionReport: { resolutionKind: "non_read" },
        turnId,
        frameId: existingFrame.frameId,
        stateVersion: 2,
        registrySnapshotId: "snapshot-write-1",
      };
      const modes: string[] = [];
      setReadAgentRunnerForTests(async (input) => {
        modes.push(input.mode);
        return outcome;
      });

      const { runId } = await createAgentRun({
        query: "处理采购申请",
        conversationId,
        turnId,
        principal: PLACEHOLDER_PRINCIPAL,
      });
      await waitForRunSettled(runId);

      const persisted = await convStore.load(conversationId, PLACEHOLDER_PRINCIPAL.principalId);
      expect(modes).toEqual(["resolve-read"]);
      expect(persisted?.stateVersion).toBe(2);
      expect(persisted?.activeFrame).toEqual(existingFrame);
      expect(persisted?.pendingInteraction?.kind ?? null).toBe(pendingKind);
    },
  );

  it("getAgentRunEvents returns [] for unknown run", async () => {
    expect(await getAgentRunEvents("run-missing", PLACEHOLDER_PRINCIPAL)).toEqual([]);
  });

  it("pending approval run recovers across store reset (cross-restart)", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c1", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);
    // simulate restart: rebind store to same dir
    const reopenedRun = new JsonlRunStore(dir);
    const reopenedConv = new JsonlConversationStore(dir);
    setDurableStoresForTests(reopenedRun, reopenedConv);
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(events.some((e) => e.state === "awaiting_approval")).toBe(true);
  });

  it("Q2 gate rejects new query while prior approval pending", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c1", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);
    await expect(createAgentRun({ query: "再次查询", conversationId: "c1", principal: PLACEHOLDER_PRINCIPAL }))
      .rejects.toThrow(/有待审批/);
  });

  it("decideAgentRunApproval loads from store and appends decision events", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const { runId: awaitingRunId } = await createAgentRun({ query: "查询库存", conversationId: "c2", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(awaitingRunId);
    // pick the awaiting run created above
    const runs = await runStore.list({ state: "awaiting_approval" });
    const target = runs[runs.length - 1];
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "已执行", approvalRecord: { id: "apr-1", status: "executed" } } as WorkbenchOutcome));
    const eventsBeforeApprove = await getAgentRunEvents(target.runId, PLACEHOLDER_PRINCIPAL);
    await decideAgentRunApproval(target.runId, "apr-1", "approve", PLACEHOLDER_PRINCIPAL);
    await waitForRunSettled(target.runId, 5000, eventsBeforeApprove.length);
    const events = await getAgentRunEvents(target.runId, PLACEHOLDER_PRINCIPAL);
    expect(events.some((e) => e.hitlState === "approved")).toBe(true);
  });

  it("resetAgentRunsForTests clears durable runs", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);
    resetAgentRunsForTests();
    expect(await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL)).toEqual([]);
  });

  it("treats a deliberately removed in-flight run as cancelled without orphan events", async () => {
    let finishRunner: (() => void) | undefined;
    setInitialReadForTests(async () => {
      await new Promise<void>((resolve) => { finishRunner = resolve; });
      return { status: "success", responseText: "late result" } as WorkbenchOutcome;
    });
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    await runStore.clearAll();
    finishRunner?.();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(await runStore.load(runId)).toBeNull();
  });

  it("resetAgentSessionsForTests clears durable sessions", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c1", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);
    resetAgentSessionsForTests();
    // after reset, Q2 gate no longer sees the prior pending run via session
    setInitialReadForTests(async () => ({ status: "success", responseText: "ok" } as WorkbenchOutcome));
    await expect(createAgentRun({ query: "新查询", conversationId: "c1", principal: PLACEHOLDER_PRINCIPAL })).resolves.toBeDefined();
  });

  it("duplicate approve continuation is idempotent (executes once)", async () => {
    let calls = 0;
    setAgentRunnerForTests(async (input) => {
      if (input.continuation) {
        calls++;
        return { status: "success", responseText: "已执行", approvalRecord: { id: "apr-1", status: "executed" } } as WorkbenchOutcome;
      }
      return awaitingOutcome("run-x");
    });
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c-idem", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);
    const eventsBeforeApprove = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    await decideAgentRunApproval(runId, "apr-1", "approve", PLACEHOLDER_PRINCIPAL);
    await waitForRunSettled(runId, 5000, eventsBeforeApprove.length);
    await decideAgentRunApproval(runId, "apr-1", "approve", PLACEHOLDER_PRINCIPAL); // duplicate
    expect(calls).toBe(1);
  });

  it("duplicate batch confirm continuation is idempotent (executes once)", async () => {
    let calls = 0;
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "resolve-read") return batchReadOutcome(input.turnId!);
      throw new Error(`unexpected READ runner mode ${input.mode}`);
    });
    setAgentRunnerForTests(async (input) => {
      if (input.continuation?.type === "batch") {
        calls++;
        return { status: "success", responseText: "批处理完成" } as WorkbenchOutcome;
      }
      throw new Error("unexpected one-shot query");
    });
    const { runId } = await createAgentRun({
      query: "批量查询",
      conversationId: "c-batch-idem",
      turnId: "turn-batch-idem",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);
    const eventsBeforeConfirm = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    await confirmAgentRunBatch(runId, PLACEHOLDER_PRINCIPAL);
    await waitForRunSettled(runId, 5000, eventsBeforeConfirm.length);
    await confirmAgentRunBatch(runId, PLACEHOLDER_PRINCIPAL); // duplicate
    expect(calls).toBe(1);
  });

  it("batch confirmation survives restart and CAS-consumes its bound pending before execution", async () => {
    let batchCalls = 0;
    let runnerPrincipal: TrustedPrincipal | undefined;
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "resolve-read") return batchReadOutcome(input.turnId!);
      throw new Error(`unexpected READ runner mode ${input.mode}`);
    });
    setAgentRunnerForTests(async (input) => {
      if (input.continuation?.type === "batch") {
        batchCalls++;
        runnerPrincipal = input.principal;
        const persisted = await convStore.load(
          "c-batch-restart",
          PLACEHOLDER_PRINCIPAL.principalId,
        );
        expect(persisted?.pendingInteraction).toBeNull();
        expect(persisted?.stateVersion).toBe(2);
        return { status: "success", responseText: "批处理完成" };
      }
      throw new Error("unexpected one-shot query");
    });

    const { runId } = await createAgentRun({
      query: "批量查询",
      conversationId: "c-batch-restart",
      turnId: "turn-batch-restart",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);
    setDurableStoresForTests(new JsonlRunStore(dir), new JsonlConversationStore(dir));
    const eventsBeforeConfirm = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);

    await confirmAgentRunBatch(runId, PLACEHOLDER_PRINCIPAL);
    await waitForRunSettled(runId, 5000, eventsBeforeConfirm.length);

    expect(batchCalls).toBe(1);
    expect(runnerPrincipal).toEqual(PLACEHOLDER_PRINCIPAL);
  });

  it("aborts an in-flight batch child when the conversation heartbeat loses its lease", async () => {
    const conversationId = "c-batch-mid-flight-loss";
    let gatewayCalls = 0;
    let abortObserved = false;
    let releaseBlockedRunner: (() => void) | undefined;
    let markRunnerStarted: (() => void) | undefined;
    const runnerStarted = new Promise<void>((resolve) => { markRunnerStarted = resolve; });

    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "resolve-read") return batchReadOutcome(input.turnId!);
      throw new Error(`unexpected READ runner mode ${input.mode}`);
    });
    const { runId } = await createAgentRun({
      query: "批量查询",
      conversationId,
      turnId: "turn-batch-mid-flight-loss",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(runId);

    let renewCalls = 0;
    const losingStore = {
      load: convStore.load.bind(convStore),
      claim: convStore.claim.bind(convStore),
      compareAndSwap: convStore.compareAndSwap.bind(convStore),
      renew: vi.fn(async (...args: Parameters<typeof convStore.renew>) => {
        renewCalls++;
        if (renewCalls === 2) return { status: "lost" as const, holder: "takeover" };
        return convStore.renew(...args);
      }),
      release: convStore.release.bind(convStore),
      lookupTurn: convStore.lookupTurn.bind(convStore),
      clear: convStore.clear.bind(convStore),
      clearAll: convStore.clearAll.bind(convStore),
    };
    setDurableStoresForTests(runStore, losingStore);
    setAgentRunnerForTests(async (input) => {
      if (input.continuation?.type !== "batch") throw new Error("unexpected continuation");
      const signal = (input as typeof input & { signal?: AbortSignal }).signal;
      gatewayCalls++;
      markRunnerStarted?.();
      await new Promise<void>((resolve, reject) => {
        releaseBlockedRunner = resolve;
        signal?.addEventListener("abort", () => {
          abortObserved = true;
          reject(signal.reason instanceof Error ? signal.reason : new Error("batch aborted"));
        }, { once: true });
      });
      gatewayCalls++;
      return { status: "success", responseText: "unexpected" };
    });

    vi.useFakeTimers();
    try {
      await confirmAgentRunBatch(runId, PLACEHOLDER_PRINCIPAL);
      await vi.advanceTimersByTimeAsync(0);
      await runnerStarted;
      await vi.advanceTimersByTimeAsync(20_000);

      expect(abortObserved).toBe(true);
      expect(gatewayCalls).toBe(1);
      await vi.advanceTimersByTimeAsync(0);
      expect((await runStore.load(runId))?.events.at(-1)).toMatchObject({
        type: "run_failed",
        error: { errorType: "CONVERSATION_BUSY" },
      });
    } finally {
      releaseBlockedRunner?.();
      await vi.advanceTimersByTimeAsync(0);
      vi.useRealTimers();
    }
  });

  it.each(["expired", "intervening-turn", "lease", "cas", "store"] as const)(
    "batch confirmation fails closed on %s with zero continuation",
    async (failure) => {
      let batchCalls = 0;
      const conversationId = `c-batch-${failure}`;
      setReadAgentRunnerForTests(async (input) => {
        if (input.mode !== "resolve-read") throw new Error(`unexpected mode ${input.mode}`);
        const outcome = batchReadOutcome(input.turnId!);
        if (failure === "expired") {
          const pending = outcome.conversationReadState!.pendingInteraction!;
          if (pending.kind !== "BATCH_CONFIRMATION") throw new Error("wrong pending kind");
          outcome.conversationReadState = {
            ...outcome.conversationReadState!,
            pendingInteraction: { ...pending, expiresAt: "2000-01-01T00:00:00Z" },
          };
          outcome.readExecutionBinding = {
            ...outcome.readExecutionBinding!,
            readState: outcome.conversationReadState,
          };
        }
        return outcome;
      });
      setAgentRunnerForTests(async (input) => {
        if (input.continuation?.type === "batch") batchCalls++;
        return { status: "success", responseText: "unexpected" };
      });
      const { runId } = await createAgentRun({
        query: "批量查询",
        conversationId,
        turnId: `turn-batch-${failure}`,
        principal: PLACEHOLDER_PRINCIPAL,
      });
      await waitForRunSettled(runId);

      if (failure === "intervening-turn") {
        const session = (await convStore.load(
          conversationId,
          PLACEHOLDER_PRINCIPAL.principalId,
        ))!;
        const pending = session.pendingInteraction!;
        await convStore.compareAndSwap(conversationId, session.stateVersion, {
          ...session,
          stateVersion: session.stateVersion + 1,
          pendingInteraction: { ...pending, stateVersion: session.stateVersion + 1 },
          lastAppliedTurnId: "turn-intervening",
          lastRunId: "run-intervening",
        });
      } else if (failure === "lease") {
        await convStore.claim(conversationId, "other-worker", 60_000);
      } else if (failure === "cas" || failure === "store") {
        const failingStore = {
          load: failure === "store"
            ? vi.fn(async () => { throw new Error("injected store failure"); })
            : convStore.load.bind(convStore),
          claim: convStore.claim.bind(convStore),
          compareAndSwap: failure === "cas"
            ? vi.fn(async () => ({ status: "conflict" as const, actualVersion: 9 }))
            : convStore.compareAndSwap.bind(convStore),
          renew: convStore.renew.bind(convStore),
          release: convStore.release.bind(convStore),
          lookupTurn: convStore.lookupTurn.bind(convStore),
          clear: convStore.clear.bind(convStore),
          clearAll: convStore.clearAll.bind(convStore),
        };
        setDurableStoresForTests(runStore, failingStore);
      }

      await expect(confirmAgentRunBatch(runId, PLACEHOLDER_PRINCIPAL)).rejects.toThrow();
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(batchCalls).toBe(0);
      if (failure === "expired") {
        expect((await convStore.load(
          conversationId,
          PLACEHOLDER_PRINCIPAL.principalId,
        ))?.pendingInteraction).toBeNull();
        expect((await runStore.load(runId))?.decision).toBe("reject");
      }
    },
  );

  it.each(["expired", "stale"] as const)(
    "lets a fresh turn reach authoritative resolution for %s batch pending",
    async (condition) => {
      const conversationId = `c-batch-recovery-${condition}`;
      let resolutionCalls = 0;
      let recoveryVersion = 2;
      setReadAgentRunnerForTests(async (input) => {
        if (input.mode !== "resolve-read") throw new Error(`unexpected mode ${input.mode}`);
        resolutionCalls++;
        if (resolutionCalls === 1) {
          const outcome = batchReadOutcome(input.turnId!);
          if (condition === "expired") {
            const pending = outcome.conversationReadState!.pendingInteraction!;
            if (pending.kind !== "BATCH_CONFIRMATION") throw new Error("wrong pending kind");
            outcome.conversationReadState = {
              ...outcome.conversationReadState!,
              pendingInteraction: { ...pending, expiresAt: "2000-01-01T00:00:00Z" },
            };
            outcome.readExecutionBinding = {
              ...outcome.readExecutionBinding!,
              readState: outcome.conversationReadState,
            };
          }
          return outcome;
        }
        expect(input.context?.readState?.pendingInteraction?.kind).toBe("BATCH_CONFIRMATION");
        return clarifyReadOutcome(input.turnId!, recoveryVersion);
      });

      const first = await createAgentRun({
        query: "批量查询",
        conversationId,
        turnId: `turn-batch-recovery-${condition}-1`,
        principal: PLACEHOLDER_PRINCIPAL,
      });
      await waitForRunSettled(first.runId);

      if (condition === "stale") {
        const session = (await convStore.load(
          conversationId,
          PLACEHOLDER_PRINCIPAL.principalId,
        ))!;
        const pending = session.pendingInteraction!;
        await convStore.compareAndSwap(conversationId, session.stateVersion, {
          ...session,
          stateVersion: session.stateVersion + 1,
          pendingInteraction: { ...pending, stateVersion: session.stateVersion },
        });
        recoveryVersion = session.stateVersion + 2;
      }

      const second = await createAgentRun({
        query: "换成单个物料查询",
        conversationId,
        turnId: `turn-batch-recovery-${condition}-2`,
        principal: PLACEHOLDER_PRINCIPAL,
      });
      await waitForRunSettled(second.runId);

      const recovered = await convStore.load(
        conversationId,
        PLACEHOLDER_PRINCIPAL.principalId,
      );
      expect(resolutionCalls).toBe(2);
      expect(recovered?.lastAppliedTurnId).toBe(`turn-batch-recovery-${condition}-2`);
      expect(recovered?.pendingInteraction?.kind).toBe("SLOT_CLARIFICATION");
    },
  );

  it("keeps a live undecided batch pending behind the Q2 gate", async () => {
    let resolutionCalls = 0;
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode !== "resolve-read") throw new Error(`unexpected mode ${input.mode}`);
      resolutionCalls++;
      return batchReadOutcome(input.turnId!);
    });
    const conversationId = "c-batch-live-q2";
    const first = await createAgentRun({
      query: "批量查询",
      conversationId,
      turnId: "turn-batch-live-q2-1",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForRunSettled(first.runId);

    await expect(createAgentRun({
      query: "发起新查询",
      conversationId,
      turnId: "turn-batch-live-q2-2",
      principal: PLACEHOLDER_PRINCIPAL,
    })).rejects.toThrow("当前对话有待审批的写操作");
    expect(resolutionCalls).toBe(1);
  });

  it("createAgentRun binds principalId to the run record", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(events.length).toBeGreaterThan(0);
    const runs = await runStore.list({ principalId: "local-user-0001" });
    expect(runs.some((r) => r.runId === runId)).toBe(true);
  });

  it("getSession writes principalId on first request and validates on subsequent", async () => {
    setInitialReadForTests(async () => ({ status: "success", responseText: "ok" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c-own", principal: PLACEHOLDER_PRINCIPAL });
    expect(runId).toBeDefined();
    await waitForRunSettled(runId);
    // second request with same principal should succeed (no throw)
    const { runId: runId2 } = await createAgentRun({ query: "再次查询", conversationId: "c-own", principal: PLACEHOLDER_PRINCIPAL });
    expect(runId2).toBeDefined();
    await waitForRunSettled(runId2);
  });

  it("getSession rejects cross-principal access to existing conversation (fail-closed)", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c-x", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);
    const attacker: TrustedPrincipal = {
      principalId: "attacker-002",
      role: "operator",
      dataScope: { tenantId: "evil" }
    };
    await expect(
      createAgentRun({ query: "越权", conversationId: "c-x", principal: attacker })
    ).rejects.toThrow(/does not belong/);
  });

  it("getAgentRunEvents returns [] for cross-principal access (fail-closed)", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const attacker: TrustedPrincipal = {
      principalId: "attacker-003",
      role: "operator",
      dataScope: { tenantId: "evil" }
    };
    expect(await getAgentRunEvents(runId, attacker)).toEqual([]);
    // same principal still sees events
    expect((await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL)).length).toBeGreaterThan(0);
  });

  it("decideAgentRunApproval throws not-found for cross-principal access", async () => {
    setAgentRunnerForTests(async () => awaitingOutcome("run-1"));
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const attacker: TrustedPrincipal = {
      principalId: "attacker-004",
      role: "operator",
      dataScope: { tenantId: "evil" }
    };
    await expect(decideAgentRunApproval(runId, "apr-1", "reject", attacker)).rejects.toThrow(/not found/);
  });

  it("confirmAgentRunBatch throws not-found for cross-principal access", async () => {
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "resolve-read") return batchReadOutcome(input.turnId!);
      throw new Error(`unexpected batch runner mode ${input.mode}`);
    });
    const { runId } = await createAgentRun({ query: "批量查询", principal: PLACEHOLDER_PRINCIPAL });
    const attacker: TrustedPrincipal = {
      principalId: "attacker-005",
      role: "operator",
      dataScope: { tenantId: "evil" }
    };
    await expect(confirmAgentRunBatch(runId, attacker)).rejects.toThrow(/not found/);
  });

  it("rejection emits run_failed terminal event after approval_state_changed", async () => {
    const runner = vi.fn(async (input: any) => {
      if (input.continuation) {
        return {
          status: "rejected",
          callPlan: { capabilityId: "cap-1", kind: "Action", agentTraceId: "t" },
          validationResult: { success: true, capabilityId: "cap-1", traceId: "g" },
          approvalRecord: { id: "apr-1", status: "rejected" },
          responseText: "审批已拒绝"
        } as WorkbenchOutcome;
      }
      return {
        status: "awaiting_approval",
        callPlan: { capabilityId: "cap-1", kind: "Action", agentTraceId: "t" },
        validationResult: { success: true, capabilityId: "cap-1", traceId: "g" },
        approvalRecord: { id: "apr-1", status: "pending" },
        responseText: "待审批"
      } as WorkbenchOutcome;
    });
    setAgentRunnerForTests(runner);
    const { runId } = await createAgentRun({ query: "创建采购申请", conversationId: "c-reject", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);
    const eventsBefore = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    await decideAgentRunApproval(runId, "apr-1", "reject", PLACEHOLDER_PRINCIPAL);
    // §1.3: continuation now runs in background; wait for rejection events
    await waitForRunSettled(runId, 5000, eventsBefore.length);
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    const lastEvent = events[events.length - 1];
    expect(lastEvent.type).toBe("run_failed");
    expect(lastEvent.error?.errorType).toBe("APPROVAL_REJECTED");
  });

  it("createAgentRun returns runId before runner produces non-started events", async () => {
    let runnerResolved = false;
    setInitialReadForTests(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
      runnerResolved = true;
      return { status: "success", responseText: "完成", callPlan: { capabilityId: "cap-test", kind: "Function" } } as WorkbenchOutcome;
    });
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    // run_started (sequence=1) is already persisted before return
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(events.length).toBe(1);
    expect(events[0].type).toBe("run_started");
    expect(runnerResolved).toBe(false);
    // after waiting, more events appear
    const settled = await waitForRunSettled(runId);
    expect(settled.some((e) => e.type === "run_completed")).toBe(true);
  });

  it("decideAgentRunApproval returns before continuation runner completes", async () => {
    let continuationResolved = false;
    setAgentRunnerForTests(async (input: any) => {
      if (input.continuation) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        continuationResolved = true;
        return { status: "success", responseText: "已执行", approvalRecord: { id: "apr-1", status: "executed" } } as WorkbenchOutcome;
      }
      return awaitingOutcome("run-1");
    });
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c-async-approval", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);
    expect(continuationResolved).toBe(false);
    const eventsBefore = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    await decideAgentRunApproval(runId, "apr-1", "approve", PLACEHOLDER_PRINCIPAL);
    // decideAgentRunApproval returns immediately; continuation not yet done
    expect(continuationResolved).toBe(false);
    const settled = await waitForRunSettled(runId, 5000, eventsBefore.length);
    expect(settled.some((e) => e.type === "run_completed")).toBe(true);
  });
});
