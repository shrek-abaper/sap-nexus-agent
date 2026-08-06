import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  createAgentRun,
  getAgentRunEvents,
  setAgentRunnerForTests,
  setDurableStoresForTests,
} from "../agent-runtime-adapter";
import { JsonlConversationStore } from "./jsonl-conversation-store";
import { JsonlRunStore } from "./jsonl-run-store";
import type { ConversationCasOutcome, SessionStateV2, WorkbenchOutcome } from "./types";
import { PLACEHOLDER_PRINCIPAL } from "../principal/types";

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
    setAgentRunnerForTests(null);
    setDurableStoresForTests(
      new JsonlRunStore(mkdtempSync(path.join(tmpdir(), "protocol-teardown-run-"))),
      new JsonlConversationStore(mkdtempSync(path.join(tmpdir(), "protocol-teardown-conv-"))),
    );
    rmSync(dir, { recursive: true, force: true });
  });

  it("persists the turn before runner execution and releases the conversation lease", async () => {
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
    vi.spyOn(conversationStore, "compareAndSwap").mockImplementation(async (...args) => {
      order.push("cas");
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
    setAgentRunnerForTests(async () => {
      order.push("runner");
      return { status: "success", responseText: "ok" } as WorkbenchOutcome;
    });

    const { runId } = await createAgentRun({
      query: "查询库存",
      conversationId: "c-order",
      turnId: "turn-order",
      principal: PLACEHOLDER_PRINCIPAL,
    });
    await waitForTerminal(runId);

    expect(order.indexOf("claim")).toBeLessThan(order.indexOf("load"));
    expect(order.indexOf("load")).toBeLessThan(order.indexOf("cas"));
    expect(order.indexOf("cas")).toBeLessThan(order.indexOf("runner"));
    expect(order.indexOf("runner")).toBeLessThan(order.indexOf("event"));
    expect(order.indexOf("event")).toBeLessThan(order.lastIndexOf("release"));
  });

  it("returns CONVERSATION_BUSY and makes zero runner calls on lease conflict", async () => {
    const runner = vi.fn(async () => ({ status: "success" } as WorkbenchOutcome));
    setAgentRunnerForTests(runner);
    await conversationStore.claim("c-busy", "other-worker", 60_000);

    await expect(createAgentRun({
      query: "查询库存",
      conversationId: "c-busy",
      turnId: "turn-busy",
      principal: PLACEHOLDER_PRINCIPAL,
    })).rejects.toMatchObject({ code: "CONVERSATION_BUSY" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("returns CONTEXT_VERSION_CONFLICT and makes zero runner calls on CAS conflict", async () => {
    const runner = vi.fn(async () => ({ status: "success" } as WorkbenchOutcome));
    setAgentRunnerForTests(runner);
    vi.spyOn(conversationStore, "compareAndSwap").mockResolvedValue({
      status: "conflict",
      actualVersion: 9,
    } as ConversationCasOutcome);

    await expect(createAgentRun({
      query: "查询库存",
      conversationId: "c-conflict",
      turnId: "turn-conflict",
      principal: PLACEHOLDER_PRINCIPAL,
    })).rejects.toMatchObject({ code: "CONTEXT_VERSION_CONFLICT" });
    expect(runner).not.toHaveBeenCalled();
  });

  it("returns the prior run for a completed duplicate turn without re-execution", async () => {
    const runner = vi.fn(async () => ({ status: "success", responseText: "ok" } as WorkbenchOutcome));
    setAgentRunnerForTests(runner);
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

  it("fails closed for an in-flight duplicate without a second runner call", async () => {
    let finish: (() => void) | undefined;
    const runner = vi.fn(async () => {
      await new Promise<void>((resolve) => { finish = resolve; });
      return { status: "success", responseText: "ok" } as WorkbenchOutcome;
    });
    setAgentRunnerForTests(runner);
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
    setAgentRunnerForTests(runner);
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
    setAgentRunnerForTests(async (input) => {
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
