import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "../../app/api/agent-runs/[runId]/stream/route";
import {
  createAgentRun,
  getAgentRunEvents,
  resetAgentRunsForTests,
  resetAgentSessionsForTests,
  setAgentRunnerForTests,
  setDurableStoresForTests
} from "./agent-runtime-adapter";
import { JsonlConversationStore } from "./durable/jsonl-conversation-store";
import { JsonlRunStore } from "./durable/jsonl-run-store";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { AgentRunEvent } from "./run-event-schema";
import type { WorkbenchOutcome } from "./durable/types";
import { PLACEHOLDER_PRINCIPAL } from "./principal/types";

async function waitForRunSettled(runId: string, timeoutMs = 5000): Promise<AgentRunEvent[]> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const events = await getAgentRunEvents(runId, PLACEHOLDER_PRINCIPAL);
    if (events.length > 0) {
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

function parseSseChunks(text: string): AgentRunEvent[] {
  return text
    .split("\n\n")
    .filter((chunk) => chunk.trim())
    .map((chunk) => {
      const dataLine = chunk.split("\n").find((line) => line.startsWith("data: "));
      return JSON.parse(dataLine!.slice(6)) as AgentRunEvent;
    });
}

async function readStream(response: Response): Promise<string> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let text = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    text += decoder.decode(value, { stream: true });
  }
  return text;
}

function request(runId: string, cursor?: number): Request {
  const url = cursor !== undefined
    ? `http://localhost/api/agent-runs/${runId}/stream?cursor=${cursor}`
    : `http://localhost/api/agent-runs/${runId}/stream`;
  return new Request(url);
}

describe("stream route", () => {
  let dir: string;
  let runStore: JsonlRunStore;
  let convStore: JsonlConversationStore;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "stream-"));
    runStore = new JsonlRunStore(dir);
    convStore = new JsonlConversationStore(dir);
    setDurableStoresForTests(runStore, convStore);
  });
  afterEach(() => {
    setAgentRunnerForTests(null);
    setDurableStoresForTests(
      new JsonlRunStore(mkdtempSync(path.join(tmpdir(), "teardown-"))),
      new JsonlConversationStore(mkdtempSync(path.join(tmpdir(), "teardown-")))
    );
    rmSync(dir, { recursive: true, force: true });
  });

  it("replays all events for a terminal run and closes stream", async () => {
    setAgentRunnerForTests(async () =>
      ({ status: "clarification", responseText: "完成" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    await waitForRunSettled(runId);

    const response = await GET(request(runId), { params: Promise.resolve({ runId }) });
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/event-stream; charset=utf-8");

    const text = await readStream(response);
    const events = parseSseChunks(text);
    expect(events.length).toBeGreaterThan(0);
    expect(events[0].type).toBe("run_started");
    expect(events[events.length - 1].type).toBe("run_completed");
  });

  it("filters events by cursor (sequence > cursor)", async () => {
    setAgentRunnerForTests(async () =>
      ({ status: "clarification", responseText: "完成" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const settled = await waitForRunSettled(runId);
    // cursor = 2: only events with sequence > 2
    const response = await GET(request(runId, 2), { params: Promise.resolve({ runId }) });
    const text = await readStream(response);
    const events = parseSseChunks(text);
    expect(events.every((e) => e.sequence > 2)).toBe(true);
    expect(events[events.length - 1].type).toBe("run_completed");
  });

  it("returns 404 for unknown run", async () => {
    const response = await GET(request("run-missing"), { params: Promise.resolve({ runId: "run-missing" }) });
    expect(response.status).toBe(404);
  });

  it("returns 400 for invalid cursor", async () => {
    const response = await GET(request("run-x", -1 as unknown as number), {
      params: Promise.resolve({ runId: "run-x" })
    });
    expect(response.status).toBe(400);
    const negativeResponse = await GET(
      new Request("http://localhost/api/agent-runs/run-x/stream?cursor=abc"),
      { params: Promise.resolve({ runId: "run-x" }) }
    );
    expect(negativeResponse.status).toBe(400);
  });

  it("closes stream immediately when cursor >= terminal sequence", async () => {
    setAgentRunnerForTests(async () =>
      ({ status: "clarification", responseText: "完成" } as WorkbenchOutcome));
    const { runId } = await createAgentRun({ query: "查询库存", principal: PLACEHOLDER_PRINCIPAL });
    const settled = await waitForRunSettled(runId);
    const terminalSeq = settled[settled.length - 1].sequence;
    const response = await GET(request(runId, terminalSeq), { params: Promise.resolve({ runId }) });
    const text = await readStream(response);
    // no new events; stream closes immediately
    expect(text).toBe("");
  });
});
