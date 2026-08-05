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
  setDurableStoresForTests
} from "./agent-runtime-adapter";
import { JsonlConversationStore } from "./durable/jsonl-conversation-store";
import { JsonlRunStore } from "./durable/jsonl-run-store";
import type { WorkbenchOutcome } from "./durable/types";
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
    setAgentRunnerForTests(async () => awaitingOutcome("run-1"));
  });
  afterEach(() => {
    setAgentRunnerForTests(null);
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
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "已执行" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    // re-arm runner to awaiting for the initial run
    setAgentRunnerForTests(async () => awaitingOutcome(runId));
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
    setAgentRunnerForTests(async () => {
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
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "ok" } as WorkbenchOutcome));
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
    const batchOutcome: WorkbenchOutcome = {
      status: "awaiting_batch_confirm",
      callPlan: { capabilityId: "cap-1", kind: "Function", agentTraceId: "t" },
      combinations: [{ k: "v1" }, { k: "v2" }]
    };
    setAgentRunnerForTests(async (input) => {
      if (input.continuation) {
        calls++;
        return { status: "success", responseText: "批处理完成" } as WorkbenchOutcome;
      }
      return batchOutcome;
    });
    const { runId } = await createAgentRun({ query: "批量查询", conversationId: "c-batch-idem", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);
    const eventsBeforeConfirm = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    await confirmAgentRunBatch(runId, PLACEHOLDER_PRINCIPAL);
    await waitForRunSettled(runId, 5000, eventsBeforeConfirm.length);
    await confirmAgentRunBatch(runId, PLACEHOLDER_PRINCIPAL); // duplicate
    expect(calls).toBe(1);
  });

  it("createAgentRun binds principalId to the run record", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    expect(events.length).toBeGreaterThan(0);
    const runs = await runStore.list({ principalId: "local-user-0001" });
    expect(runs.some((r) => r.runId === runId)).toBe(true);
  });

  it("getSession writes principalId on first request and validates on subsequent", async () => {
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "ok" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c-own", principal: PLACEHOLDER_PRINCIPAL });
    expect(runId).toBeDefined();
    // second request with same principal should succeed (no throw)
    const { runId: runId2 } = await createAgentRun({ query: "再次查询", conversationId: "c-own", principal: PLACEHOLDER_PRINCIPAL });
    expect(runId2).toBeDefined();
  });

  it("getSession rejects cross-principal access to existing conversation (fail-closed)", async () => {
    await createAgentRun({ query: "查询库存", conversationId: "c-x", principal: PLACEHOLDER_PRINCIPAL });
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
    setAgentRunnerForTests(async () => ({
      status: "awaiting_batch_confirm",
      callPlan: { capabilityId: "cap-1", kind: "Action" },
      combinations: [{ plant: "P1" }],
      responseText: "待确认"
    } as WorkbenchOutcome));
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
    setAgentRunnerForTests(async () => {
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
