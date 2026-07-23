import { describe, expect, it } from "vitest";
import { buildWorkbenchViewModel, summarizeTurn } from "../../src/modules/agent-console/view-model";
import type { ChatTurn } from "../../src/modules/agent-console/chat-types";
import type { AgentRunSnapshot } from "../../src/runtime/run-event-schema";

const completedSnapshot: AgentRunSnapshot = {
  runId: "run-1",
  state: "completed",
  hitlState: "approval_not_required",
  events: [
    {
      runId: "run-1",
      sequence: 1,
      timestamp: "2026-07-09T00:00:00.000Z",
      type: "narrative_created",
      state: "narrated",
      artifact: {
        label: "Chinese Narrative",
        kind: "narrative",
        payload: { text: "物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。" }
      }
    }
  ]
};

describe("summarizeTurn", () => {
  it("truncates a long query to 20 chars with ellipsis and reports snapshot state", () => {
    const turn: ChatTurn = {
      runId: "run-x",
      query: "DEMOA1 在 1000 还有多少可用库存？再加一点长度",
      snapshot: completedSnapshot,
      isRunning: false
    };
    const summary = summarizeTurn(turn);
    expect(summary.label.endsWith("…")).toBe(true);
    expect(summary.label.length).toBeLessThanOrEqual(21);
    expect(summary.state).toBe(completedSnapshot.state);
  });

  it("keeps a short query as-is", () => {
    const turn: ChatTurn = {
      runId: "run-y",
      query: "查库存",
      snapshot: null,
      isRunning: false
    };
    expect(summarizeTurn(turn).label).toBe("查库存");
    expect(summarizeTurn(turn).state).toBe("等待运行");
  });

  it("falls back to running state when snapshot is null but turn is running", () => {
    const turn: ChatTurn = {
      runId: "run-z",
      query: "查库存",
      snapshot: null,
      isRunning: true
    };
    expect(summarizeTurn(turn).state).toBe("running");
  });

  it("falls back to 新对话 label for empty query", () => {
    const turn: ChatTurn = {
      runId: "run-empty",
      query: "   ",
      snapshot: null,
      isRunning: false
    };
    expect(summarizeTurn(turn).label).toBe("新对话");
  });

  it("reports 失败 state when turn has a transport-layer error", () => {
    const turn: ChatTurn = {
      runId: "run-err",
      query: "查库存",
      snapshot: null,
      isRunning: false,
      error: "请求失败（HTTP 500）"
    };
    expect(summarizeTurn(turn).state).toBe("失败");
  });
});

// 既有 buildWorkbenchViewModel 行为不被 summarizeTurn 引入破坏
describe("buildWorkbenchViewModel regression after summarizeTurn addition", () => {
  it("still produces the success narrative result", () => {
    const view = buildWorkbenchViewModel(completedSnapshot);
    expect(view.result.tone).toBe("success");
    expect(view.result.body).toContain("DEMOA1");
  });
});
