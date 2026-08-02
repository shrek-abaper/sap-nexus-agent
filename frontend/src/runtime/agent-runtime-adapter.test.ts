import { afterEach, beforeEach, describe, expect, it } from "vitest";
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

function awaitingOutcome(runId: string): WorkbenchOutcome {
  return {
    status: "awaiting_approval",
    callPlan: { capabilityId: "cap-1", kind: "Action", agentTraceId: "t" },
    validationResult: { success: true, capabilityId: "cap-1", traceId: "g" },
    approvalRecord: { id: "apr-1", status: "pending" },
    responseText: "待审批"
  };
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
    const { runId } = await createAgentRun({ query: "查询库存" });
    const events = await getAgentRunEvents(runId);
    expect(events.length).toBeGreaterThan(0);
    expect(events[0].type).toBe("run_started");
  });

  it("getAgentRunEvents returns [] for unknown run", async () => {
    expect(await getAgentRunEvents("run-missing")).toEqual([]);
  });

  it("pending approval run recovers across store reset (cross-restart)", async () => {
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c1" });
    // simulate restart: rebind store to same dir
    const reopenedRun = new JsonlRunStore(dir);
    const reopenedConv = new JsonlConversationStore(dir);
    setDurableStoresForTests(reopenedRun, reopenedConv);
    const events = await getAgentRunEvents(runId);
    expect(events.some((e) => e.state === "awaiting_approval")).toBe(true);
  });

  it("Q2 gate rejects new query while prior approval pending", async () => {
    await createAgentRun({ query: "查询库存", conversationId: "c1" });
    await expect(createAgentRun({ query: "再次查询", conversationId: "c1" }))
      .rejects.toThrow(/有待审批/);
  });

  it("decideAgentRunApproval loads from store and appends decision events", async () => {
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "已执行" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存" });
    // re-arm runner to awaiting for the initial run
    setAgentRunnerForTests(async () => awaitingOutcome(runId));
    await createAgentRun({ query: "查询库存", conversationId: "c2" }).catch(() => {});
    // pick the awaiting run created above
    const runs = await runStore.list({ state: "awaiting_approval" });
    const target = runs[runs.length - 1];
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "已执行", approvalRecord: { id: "apr-1", status: "executed" } } as WorkbenchOutcome));
    await decideAgentRunApproval(target.runId, "approve");
    const events = await getAgentRunEvents(target.runId);
    expect(events.some((e) => e.hitlState === "approved")).toBe(true);
  });

  it("resetAgentRunsForTests clears durable runs", async () => {
    const { runId } = await createAgentRun({ query: "查询库存" });
    resetAgentRunsForTests();
    expect(await getAgentRunEvents(runId)).toEqual([]);
  });

  it("resetAgentSessionsForTests clears durable sessions", async () => {
    await createAgentRun({ query: "查询库存", conversationId: "c1" });
    resetAgentSessionsForTests();
    // after reset, Q2 gate no longer sees the prior pending run via session
    setAgentRunnerForTests(async () => ({ status: "success", responseText: "ok" } as WorkbenchOutcome));
    await expect(createAgentRun({ query: "新查询", conversationId: "c1" })).resolves.toBeDefined();
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
    const { runId } = await createAgentRun({ query: "查询库存", conversationId: "c-idem" });
    await decideAgentRunApproval(runId, "approve");
    await decideAgentRunApproval(runId, "approve"); // duplicate
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
    const { runId } = await createAgentRun({ query: "批量查询", conversationId: "c-batch-idem" });
    await confirmAgentRunBatch(runId);
    await confirmAgentRunBatch(runId); // duplicate
    expect(calls).toBe(1);
  });
});
