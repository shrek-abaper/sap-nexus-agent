import { describe, expect, it } from "vitest";
import { buildChatBubbleState } from "../../src/modules/agent-console/view-model";
import type { ChatTurn } from "../../src/modules/agent-console/chat-types";
import type { AgentRunSnapshot } from "../../src/runtime/run-event-schema";

const narrativeSnapshot: AgentRunSnapshot = {
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

const runningSnapshot: AgentRunSnapshot = {
  runId: "run-2",
  state: "running",
  hitlState: "approval_not_required",
  events: [
    {
      runId: "run-2",
      sequence: 1,
      timestamp: "2026-07-09T00:00:01.000Z",
      type: "intent_parsed",
      state: "intent_parsed",
      artifact: { label: "IntentParseResult", kind: "intent", payload: {} }
    }
  ]
};

describe("buildChatBubbleState - AI 气泡流式占位与 narrative 切换", () => {
  it("shows streaming cursor placeholder while running and no narrative yet", () => {
    const turn: ChatTurn = {
      runId: "run-2",
      query: "查库存",
      snapshot: runningSnapshot,
      isRunning: true
    };
    const bubble = buildChatBubbleState(turn);
    expect(bubble.hasNarrative).toBe(false);
    expect(bubble.showStreaming).toBe(true);
    expect(bubble.placeholder).toBe("正在推理");
  });

  it("shows narrative body once narrative arrives and run settles", () => {
    const turn: ChatTurn = {
      runId: "run-1",
      query: "查库存",
      snapshot: narrativeSnapshot,
      isRunning: false
    };
    const bubble = buildChatBubbleState(turn);
    expect(bubble.hasNarrative).toBe(true);
    expect(bubble.showStreaming).toBe(false);
  });

  it("shows idle placeholder before any run (snapshot null, not running)", () => {
    const turn: ChatTurn = {
      runId: "run-0",
      query: "",
      snapshot: null,
      isRunning: false
    };
    const bubble = buildChatBubbleState(turn);
    expect(bubble.hasNarrative).toBe(false);
    expect(bubble.showStreaming).toBe(false);
    expect(bubble.placeholder).toContain("输入问题后");
  });
});

describe("多轮消息累积数据模型", () => {
  it("each turn is an independent run with its own snapshot, no cross-turn context", () => {
    const turn1: ChatTurn = {
      runId: "run-1",
      query: "第一轮查询",
      snapshot: narrativeSnapshot,
      isRunning: false
    };
    const turn2: ChatTurn = {
      runId: "run-2",
      query: "第二轮查询",
      snapshot: runningSnapshot,
      isRunning: true
    };
    const turns = [turn1, turn2];

    // 多轮累积：两轮消息都保留
    expect(turns).toHaveLength(2);
    // 各轮独立 snapshot，互不影响
    expect(buildChatBubbleState(turns[0]).hasNarrative).toBe(true);
    expect(buildChatBubbleState(turns[1]).showStreaming).toBe(true);
    // runId 唯一
    expect(new Set(turns.map((t) => t.runId)).size).toBe(2);
  });
});
