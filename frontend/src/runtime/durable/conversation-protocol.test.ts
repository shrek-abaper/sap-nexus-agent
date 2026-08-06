import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  createAgentRun,
  getAgentRunEvents,
  setReadAgentRunnerForTests,
  setCompositionGatewayForTests,
  setDurableStoresForTests,
} from "../agent-runtime-adapter";
import { JsonlConversationStore } from "./jsonl-conversation-store";
import { JsonlRunStore } from "./jsonl-run-store";
import { canonicalJson, sha256Hex } from "./canonical-json";
import type { ConversationCasOutcome, SessionStateV2, WorkbenchOutcome } from "./types";
import { FakeGateway } from "../plan-executor/fake-gateway";
import { PLACEHOLDER_PRINCIPAL } from "../principal/types";

function compositionHandoff(): WorkbenchOutcome {
  return {
    status: "match_decision",
    matchDecision: {
      decisionType: "ESCALATE_TO_PLANNER",
      handoff: { registrySnapshotId: "snapshot-lease-gate" },
    },
    dryRun: {
      gaps: [],
      planGraph: {
        planGraphVersion: 2,
        planId: "plan-lease-gate",
        goalId: "goal-lease-gate",
        executionMode: "advisory",
        snapshotId: "snapshot-lease-gate",
        nodes: [{
          nodeId: "node.inventory",
          capabilityId: "MM.Inventory.GetAvailability",
          parameterBindings: [
            {
              parameterName: "material",
              source: { kind: "literal", semanticType: "MaterialCode", value: "MAT-1" },
            },
            {
              parameterName: "plant",
              source: { kind: "literal", semanticType: "PlantCode", value: "P1" },
            },
          ],
          producesFactTypes: ["InventoryAvailability"],
          governance: { requiresApproval: false },
        }],
        edges: [],
        topologicalOrder: ["node.inventory"],
        goalOutputs: [],
        readPartition: ["node.inventory"],
        actionPartition: [],
        projectionRef: [],
        ruleSetRefs: [],
      },
    },
  };
}

function resolvedReadOutcome(turnId: string): WorkbenchOutcome {
  const callPlan = {
    agentTraceId: "agent-protocol-read",
    capabilityId: "MM.Inventory.GetAvailability",
    kind: "Function",
    parameters: { material: "DEMOA2", plant: "1000", unit: "EA" },
    validationPolicy: "validate_before_execute",
    createdBy: "agent",
    requiresApproval: false,
  };
  const readState = {
    activeFrame: {
      frameId: "frame-protocol-read",
      capabilityId: callPlan.capabilityId,
      slots: {},
      status: "READY" as const,
      createdTurnId: turnId,
      updatedTurnId: turnId,
      registrySnapshotId: "snapshot-protocol-read",
      capabilityVersion: "1",
    },
    recentFrames: [],
    pendingInteraction: null,
    stateVersion: 1,
  };
  return {
    status: "resolved_read",
    callPlan,
    matchDecision: { decisionType: "SELECT", capabilityId: callPlan.capabilityId },
    decision: { decisionType: "SELECT", capabilityId: callPlan.capabilityId },
    conversationReadState: readState,
    resolutionReport: { frameStatus: "READY" },
    turnId,
    frameId: readState.activeFrame.frameId,
    stateVersion: 1,
    registrySnapshotId: readState.activeFrame.registrySnapshotId,
    readExecutionBinding: {
      turnId,
      frameId: readState.activeFrame.frameId,
      stateVersion: 1,
      registrySnapshotId: readState.activeFrame.registrySnapshotId,
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      capabilityVersion: "1",
      executorBindingId: "sap.mm.inventory.md04-stock-req-list",
      callPlanHash: sha256Hex(canonicalJson(callPlan)),
      readState,
    },
  };
}

async function waitForTerminal(runId: string): Promise<void> {
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    if (events.some((event) => event.type === "run_completed" || event.type === "run_failed")) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`Run ${runId} did not become terminal`);
}

describe("durable conversation protocol", () => {
  let dir: string;
  let runStore: JsonlRunStore;
  let conversationStore: JsonlConversationStore;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "conversation-protocol-"));
    runStore = new JsonlRunStore(dir);
    conversationStore = new JsonlConversationStore(dir);
    setDurableStoresForTests(runStore, conversationStore);
  });

  afterEach(() => {
    vi.useRealTimers();
    setReadAgentRunnerForTests(null);
    setCompositionGatewayForTests(null);
    setDurableStoresForTests(
      new JsonlRunStore(mkdtempSync(path.join(tmpdir(), "protocol-teardown-run-"))),
      new JsonlConversationStore(mkdtempSync(path.join(tmpdir(), "protocol-teardown-conv-"))),
    );
    rmSync(dir, { recursive: true, force: true });
  });

  it("resolves before CAS and releases the conversation lease after persistence", async () => {
    const order: string[] = [];
    const claim = conversationStore.claim.bind(conversationStore);
    const load = conversationStore.load.bind(conversationStore);
    const compareAndSwap = conversationStore.compareAndSwap.bind(conversationStore);
    const release = conversationStore.release.bind(conversationStore);
    vi.spyOn(conversationStore, "claim").mockImplementation(async (...args) => {
      order.push("claim");
      return claim(...args);
    });
    vi.spyOn(conversationStore, "load").mockImplementation(async (...args) => {
      order.push("load");
      return load(...args);
    });
    let casCount = 0;
    vi.spyOn(conversationStore, "compareAndSwap").mockImplementation(async (...args) => {
      order.push(`cas-${++casCount}`);
      return compareAndSwap(...args);
    });
    vi.spyOn(conversationStore, "release").mockImplementation(async (...args) => {
      order.push("release");
      return release(...args);
    });
    const appendEvent = runStore.appendEvent.bind(runStore);
    vi.spyOn(runStore, "appendEvent").mockImplementation(async (...args) => {
      order.push("event");
      return appendEvent(...args);
    });
    setReadAgentRunnerForTests(async (input) => {
      if (input.mode === "resolve-read") {
        order.push("resolve");
        return resolvedReadOutcome(input.turnId!);
      }
      if (input.mode === "continue-read") {
        order.push("continue");
        return { status: "success", responseText: "ok" } as WorkbenchOutcome;
      }
      throw new Error(`unexpected mode ${input.mode}`);
    });

    const { runId } = await createAgentRun({
      query: "查询库存",
      conversationId: "c-order",
      turnId: "turn-order",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(runId);

    expect(order.indexOf("claim")).toBeLessThan(order.indexOf("load"));
    expect(order.indexOf("load")).toBeLessThan(order.indexOf("resolve"));
    expect(order.indexOf("resolve")).toBeLessThan(order.indexOf("cas-1"));
    expect(order.indexOf("cas-1")).toBeLessThan(order.indexOf("continue"));
    expect(order.indexOf("continue")).toBeLessThan(order.indexOf("cas-2"));
    expect(order.indexOf("cas-2")).toBeLessThan(order.indexOf("event"));
    expect(casCount).toBe(2);
    expect(order.indexOf("event")).toBeLessThan(order.lastIndexOf("release"));
  });

  it("returns CONVERSATION_BUSY and makes zero runner calls on lease conflict", async () => {
    const runner = vi.fn(async () => ({ status: "success" } as WorkbenchOutcome));
    setReadAgentRunnerForTests(runner);
    await conversationStore.claim("c-busy", "other-worker", 60_000);

    await expect(createAgentRun({
      query: "查询库存",
      conversationId: "c-busy",
      turnId: "turn-busy",
      principal: PLACEHOLDER_PRINCIPAL,
    })).rejects.toMatchObject({ code: "CONVERSATION_BUSY" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("records CONTEXT_VERSION_CONFLICT after resolution loses CAS", async () => {
    const runner = vi.fn(async () => ({ status: "success" } as WorkbenchOutcome));
    setReadAgentRunnerForTests(runner);
    vi.spyOn(conversationStore, "compareAndSwap").mockResolvedValue({
      status: "conflict",
      actualVersion: 9,
    } as ConversationCasOutcome);

    const { runId } = await createAgentRun({
      query: "查询库存",
      conversationId: "c-conflict",
      turnId: "turn-conflict",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(runId);

    expect((await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL)).at(-1)).toMatchObject({
      type: "run_failed",
      error: { errorType: "CONTEXT_VERSION_CONFLICT" },
    });
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("fails after resolution when the fenced lease is taken over after CAS", async () => {
    const now = Date.now();
    const runner = vi.fn(async () => ({ status: "success" } as WorkbenchOutcome));
    setReadAgentRunnerForTests(runner);
    const compareAndSwap = conversationStore.compareAndSwap.bind(conversationStore);
    let takeover: Awaited<ReturnType<JsonlConversationStore["claim"]>> | undefined;
    vi.spyOn(conversationStore, "compareAndSwap").mockImplementation(async (...args) => {
      const saved = await compareAndSwap(...args);
      const clock = vi.spyOn(Date, "now").mockReturnValue(now + 120_001);
      takeover = await new JsonlConversationStore(dir).claim("c-fenced-before-runner", "new-owner", 60_000);
      clock.mockRestore();
      return saved;
    });

    const { runId } = await createAgentRun({
      query: "查询库存",
      conversationId: "c-fenced-before-runner",
      turnId: "turn-fenced-before-runner",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(runId);

    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(takeover).toMatchObject({ status: "force-claimed", previousHolder: expect.any(String) });
    expect(events.at(-1)).toMatchObject({
      type: "run_failed",
      error: { errorType: "CONVERSATION_BUSY" },
    });
    expect(runner).toHaveBeenCalledTimes(1);
    expect(await new JsonlConversationStore(dir).claim(
      "c-fenced-before-runner",
      "third-owner",
      60_000,
    )).toMatchObject({ status: "rejected", holder: "new-owner" });
  });

  it("prevents a stale runner from persisting after lease takeover", async () => {
    const now = Date.now();
    let finish: (() => void) | undefined;
    let started: (() => void) | undefined;
    const runnerStarted = new Promise<void>((resolve) => { started = resolve; });
    const runner = vi.fn(async () => {
      started?.();
      await new Promise<void>((resolve) => { finish = resolve; });
      return { status: "success", responseText: "stale result" } as WorkbenchOutcome;
    });
    setReadAgentRunnerForTests(runner);
    const { runId } = await createAgentRun({
      query: "查询库存",
      conversationId: "c-fenced-result",
      turnId: "turn-fenced-result",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await runnerStarted;
    const clock = vi.spyOn(Date, "now").mockReturnValue(now + 120_001);
    const takeover = await new JsonlConversationStore(dir).claim("c-fenced-result", "new-owner", 60_000);
    clock.mockRestore();
    finish?.();
    await waitForTerminal(runId);

    const session = await new JsonlConversationStore(dir).load(
      "c-fenced-result",
      PLACEHOLDER_PRINCIPAL.principalId,
    );
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(takeover).toMatchObject({ status: "force-claimed" });
    expect(session).toBeNull();
    expect(events.at(-1)).toMatchObject({
      type: "run_failed",
      error: { errorType: "CONVERSATION_BUSY" },
    });
    expect(await new JsonlConversationStore(dir).claim("c-fenced-result", "third-owner", 60_000))
      .toMatchObject({ status: "rejected", holder: "new-owner" });
  });

  it("blocks composition and Gateway immediately after a stale runner returns", async () => {
    const now = Date.now();
    let finish: (() => void) | undefined;
    let started: (() => void) | undefined;
    const runnerStarted = new Promise<void>((resolve) => { started = resolve; });
    setReadAgentRunnerForTests(async () => {
      started?.();
      await new Promise<void>((resolve) => { finish = resolve; });
      return compositionHandoff();
    });
    const gateway = new FakeGateway();
    setCompositionGatewayForTests(gateway);
    const { runId } = await createAgentRun({
      query: "compose inventory",
      conversationId: "c-post-run-lease-gate",
      turnId: "turn-post-run-lease-gate",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await runnerStarted;
    const clock = vi.spyOn(Date, "now").mockReturnValue(now + 120_001);
    const takeover = await new JsonlConversationStore(dir).claim(
      "c-post-run-lease-gate",
      "new-owner",
      60_000,
    );
    clock.mockRestore();
    finish?.();
    await waitForTerminal(runId);

    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(takeover).toMatchObject({ status: "force-claimed" });
    expect(events.at(-1)).toMatchObject({
      type: "run_failed",
      error: { errorType: "CONVERSATION_BUSY" },
    });
    expect(gateway.validateCalls).toHaveLength(0);
    expect(gateway.executeCalls).toHaveLength(0);
    expect(await new JsonlConversationStore(dir).claim(
      "c-post-run-lease-gate",
      "third-owner",
      60_000,
    )).toMatchObject({ status: "rejected", holder: "new-owner" });
  });

  it("renews the conversation lease while the runner is blocked and stops the heartbeat in finally", async () => {
    vi.useFakeTimers();
    let finish: (() => void) | undefined;
    let renewCalls = 0;
    const heartbeatStore = new Proxy(conversationStore, {
      get(target, property) {
        if (property === "renew") {
          return async (...args: unknown[]) => {
            renewCalls += 1;
            const renew = Reflect.get(target, property) as ((...values: unknown[]) => unknown) | undefined;
            return renew?.apply(target, args);
          };
        }
        const value = Reflect.get(target, property);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
    setDurableStoresForTests(runStore, heartbeatStore);
    setReadAgentRunnerForTests(async () => {
      await new Promise<void>((resolve) => { finish = resolve; });
      return { status: "clarification", responseText: "ok" } as WorkbenchOutcome;
    });

    const started = createAgentRun({
      query: "查询库存",
      conversationId: "c-heartbeat",
      turnId: "turn-heartbeat",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await vi.advanceTimersByTimeAsync(0);
    const { runId } = await started;
    await vi.advanceTimersByTimeAsync(20_000);
    const callsWhileBlocked = renewCalls;

    finish?.();
    await vi.advanceTimersByTimeAsync(0);
    const record = await runStore.load(runId);
    expect(record?.events.at(-1)?.type).toBe("run_completed");
    const callsAfterCompletion = renewCalls;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(callsWhileBlocked).toBeGreaterThan(1);
    expect(renewCalls).toBe(callsAfterCompletion);
  });

  it("returns the prior run for a completed duplicate turn without re-execution", async () => {
    const runner = vi.fn(async () => ({ status: "success", responseText: "ok" } as WorkbenchOutcome));
    setReadAgentRunnerForTests(runner);
    const input = {
      query: "查询库存",
      conversationId: "c-duplicate",
      turnId: "turn-stable",
      principal: PLACEHOLDER_PRINCIPAL,
    };

    const first = await createAgentRun(input);
    await waitForTerminal(first.runId);
    const duplicate = await createAgentRun(input);

    expect(duplicate).toEqual({ runId: first.runId, turnId: "turn-stable" });
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("returns an older completed turn after an intervening turn and restart without re-execution", async () => {
    const runner = vi.fn(async ({ query }) => ({
      status: "success",
      responseText: `result:${query}`,
    } as WorkbenchOutcome));
    setReadAgentRunnerForTests(runner);
    const first = await createAgentRun({
      query: "first query",
      conversationId: "c-historical-completed",
      turnId: "turn-first",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(first.runId);
    const second = await createAgentRun({
      query: "second query",
      conversationId: "c-historical-completed",
      turnId: "turn-second",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(second.runId);

    runStore = new JsonlRunStore(dir);
    conversationStore = new JsonlConversationStore(dir);
    setDurableStoresForTests(runStore, conversationStore);
    const retried = await createAgentRun({
      query: "first query",
      conversationId: "c-historical-completed",
      turnId: "turn-first",
      principal: PLACEHOLDER_PRINCIPAL,
    });

    expect(retried).toEqual({ runId: first.runId, turnId: "turn-first" });
    expect(runner).toHaveBeenCalledTimes(2);
  });

  it("recovers a completed turn after ledger commit failure, restart, and an intervening turn", async () => {
    let failLedgerRename = true;
    conversationStore = new JsonlConversationStore(dir, (boundary) => {
      if (failLedgerRename && boundary.artifact === "turn-ledger" && boundary.phase === "before-rename") {
        failLedgerRename = false;
        throw new Error("injected ledger rename failure");
      }
    });
    setDurableStoresForTests(runStore, conversationStore);
    setReadAgentRunnerForTests(async () => ({ status: "success", responseText: "original" }));
    const originalInput = {
      query: "original query",
      conversationId: "c-ledger-recovery-completed",
      turnId: "turn-original-completed",
      principal: PLACEHOLDER_PRINCIPAL,
    };
    const original = await createAgentRun(originalInput);
    await waitForTerminal(original.runId);
    expect((await getAgentRunEvents(original.runId, PLACEHOLDER_PRINCIPAL)).at(-1)?.type)
      .toBe("run_failed");
    const committed = JSON.parse(readFileSync(
      path.join(dir, "sessions", "c-ledger-recovery-completed.json"),
      "utf8",
    )) as SessionStateV2;
    await runStore.save(committed.lastRunId!, {
      runId: committed.lastRunId!,
      query: originalInput.query,
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      events: [
        {
          runId: committed.lastRunId!,
          sequence: 1,
          timestamp: new Date().toISOString(),
          type: "run_started",
          state: "running",
        },
        {
          runId: committed.lastRunId!,
          sequence: 2,
          timestamp: new Date().toISOString(),
          type: "run_completed",
          state: "completed",
        },
      ],
    });

    runStore = new JsonlRunStore(dir);
    conversationStore = new JsonlConversationStore(dir);
    setDurableStoresForTests(runStore, conversationStore);
    const runner = vi.fn(async () => ({ status: "clarification", responseText: "intervening" } as WorkbenchOutcome));
    setReadAgentRunnerForTests(runner);
    const intervening = await createAgentRun({
      query: "intervening query",
      conversationId: originalInput.conversationId,
      turnId: "turn-intervening-after-recovery",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(intervening.runId);
    const retried = await createAgentRun(originalInput);

    expect(retried).toEqual({ runId: committed.lastRunId, turnId: originalInput.turnId });
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("fails closed for an in-flight duplicate without a second runner call", async () => {
    let finish: (() => void) | undefined;
    const runner = vi.fn(async () => {
      await new Promise<void>((resolve) => { finish = resolve; });
      return { status: "success", responseText: "ok" } as WorkbenchOutcome;
    });
    setReadAgentRunnerForTests(runner);
    const input = {
      query: "查询库存",
      conversationId: "c-inflight",
      turnId: "turn-inflight",
      principal: PLACEHOLDER_PRINCIPAL,
    };

    const first = await createAgentRun(input);
    await expect(createAgentRun(input)).rejects.toMatchObject({ code: "CONVERSATION_BUSY" });
    expect(runner).toHaveBeenCalledTimes(1);

    finish?.();
    await waitForTerminal(first.runId);
  });

  it("does not replay a persisted turn whose run never became terminal", async () => {
    const runner = vi.fn(async () => ({ status: "success" } as WorkbenchOutcome));
    setReadAgentRunnerForTests(runner);
    await runStore.save("run-crashed", {
      runId: "run-crashed",
      query: "查询库存",
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      events: [{
        runId: "run-crashed",
        sequence: 1,
        timestamp: new Date().toISOString(),
        type: "run_started",
        state: "running",
      }],
    });
    const crashed: SessionStateV2 = {
      schemaVersion: 2,
      stateVersion: 1,
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      activeFrame: null,
      recentFrames: [],
      pendingInteraction: null,
      history: [{ role: "user", content: "查询库存" }],
      lastAppliedTurnId: "turn-crashed",
      lastRunId: "run-crashed",
    };
    await conversationStore.compareAndSwap("c-crashed", 0, crashed);

    await expect(createAgentRun({
      query: "查询库存",
      conversationId: "c-crashed",
      turnId: "turn-crashed",
      principal: PLACEHOLDER_PRINCIPAL,
    })).rejects.toMatchObject({ code: "CONVERSATION_TURN_IN_FLIGHT" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("keeps an older crashed turn non-replayable after an intervening turn and restart", async () => {
    await runStore.save("run-crashed-older", {
      runId: "run-crashed-older",
      query: "older query",
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      events: [{
        runId: "run-crashed-older",
        sequence: 1,
        timestamp: new Date().toISOString(),
        type: "run_started",
        state: "running",
      }],
    });
    await conversationStore.compareAndSwap("c-historical-crashed", 0, {
      schemaVersion: 2,
      stateVersion: 1,
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      activeFrame: null,
      recentFrames: [],
      pendingInteraction: null,
      history: [{ role: "user", content: "older query" }],
      lastAppliedTurnId: "turn-crashed-older",
      lastRunId: "run-crashed-older",
    });
    const runner = vi.fn(async () => ({ status: "success", responseText: "new result" } as WorkbenchOutcome));
    setReadAgentRunnerForTests(runner);
    const intervening = await createAgentRun({
      query: "intervening query",
      conversationId: "c-historical-crashed",
      turnId: "turn-intervening",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(intervening.runId);

    runStore = new JsonlRunStore(dir);
    conversationStore = new JsonlConversationStore(dir);
    setDurableStoresForTests(runStore, conversationStore);
    await expect(createAgentRun({
      query: "older query",
      conversationId: "c-historical-crashed",
      turnId: "turn-crashed-older",
      principal: PLACEHOLDER_PRINCIPAL,
    })).rejects.toMatchObject({ code: "CONVERSATION_TURN_IN_FLIGHT" });
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("recovers a non-terminal turn after ledger commit failure, restart, and an intervening turn", async () => {
    let failLedgerRename = true;
    conversationStore = new JsonlConversationStore(dir, (boundary) => {
      if (failLedgerRename && boundary.artifact === "turn-ledger" && boundary.phase === "before-rename") {
        failLedgerRename = false;
        throw new Error("injected ledger rename failure");
      }
    });
    setDurableStoresForTests(runStore, conversationStore);
    setReadAgentRunnerForTests(async () => ({ status: "success", responseText: "original" }));
    const originalInput = {
      query: "crashed original query",
      conversationId: "c-ledger-recovery-crashed",
      turnId: "turn-original-crashed",
      principal: PLACEHOLDER_PRINCIPAL,
    };
    const original = await createAgentRun(originalInput);
    await waitForTerminal(original.runId);
    expect((await getAgentRunEvents(original.runId, PLACEHOLDER_PRINCIPAL)).at(-1)?.type)
      .toBe("run_failed");
    const committed = JSON.parse(readFileSync(
      path.join(dir, "sessions", "c-ledger-recovery-crashed.json"),
      "utf8",
    )) as SessionStateV2;
    await runStore.save(committed.lastRunId!, {
      runId: committed.lastRunId!,
      query: originalInput.query,
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      events: [{
        runId: committed.lastRunId!,
        sequence: 1,
        timestamp: new Date().toISOString(),
        type: "run_started",
        state: "running",
      }],
    });

    runStore = new JsonlRunStore(dir);
    conversationStore = new JsonlConversationStore(dir);
    setDurableStoresForTests(runStore, conversationStore);
    const runner = vi.fn(async () => ({ status: "clarification", responseText: "intervening" } as WorkbenchOutcome));
    setReadAgentRunnerForTests(runner);
    const intervening = await createAgentRun({
      query: "intervening query",
      conversationId: originalInput.conversationId,
      turnId: "turn-intervening-after-crash",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(intervening.runId);

    await expect(createAgentRun(originalInput))
      .rejects.toMatchObject({ code: "CONVERSATION_TURN_IN_FLIGHT" });
    expect(runner).toHaveBeenCalledTimes(1);
  });

  it("does not promote a persisted READ frame into WRITE approval authority", async () => {
    const session: SessionStateV2 = {
      schemaVersion: 2,
      stateVersion: 1,
      principalId: PLACEHOLDER_PRINCIPAL.principalId,
      activeFrame: {
        frameId: "frame-write-shaped",
        capabilityId: "MM.PR.CreateDraft",
        slots: {},
        status: "READY",
        createdTurnId: "turn-previous",
        updatedTurnId: "turn-previous",
        registrySnapshotId: "snapshot-1",
        capabilityVersion: "1.0.0",
      },
      recentFrames: [],
      pendingInteraction: null,
      history: [{ role: "user", content: "create a purchase requisition" }],
      lastAppliedTurnId: "turn-previous",
      lastRunId: null,
    };
    await conversationStore.compareAndSwap("c-write-shaped", 0, session);
    let receivedLastContext: unknown = "not-called";
    setReadAgentRunnerForTests(async (input) => {
      receivedLastContext = input.context?.lastContext;
      return { status: "success", responseText: "no write authority" } as WorkbenchOutcome;
    });

    const { runId } = await createAgentRun({
      query: "continue",
      conversationId: "c-write-shaped",
      turnId: "turn-current",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(runId);

    expect(receivedLastContext).toBeNull();
    expect((await runStore.load(runId))?.pendingOutcome).toBeUndefined();
  });
});
