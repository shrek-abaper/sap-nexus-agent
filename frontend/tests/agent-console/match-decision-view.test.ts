import { describe, expect, it } from "vitest";
import {
  buildChatBubbleState,
  buildMatchDecisionView,
  buildWorkbenchViewModel,
  summarizeTurn
} from "../../src/modules/agent-console/view-model";
import type { ChatTurn } from "../../src/modules/agent-console/chat-types";
import type { AgentRunSnapshot, AgentRunEvent } from "../../src/runtime/run-event-schema";
import type { JsonValue } from "../../src/shared/types/artifacts";

const baseEvent = {
  runId: "run-md",
  sequence: 1,
  timestamp: "2026-07-25T00:00:00.000Z"
} as const;

function matchDecisionEvent(
  payload: JsonValue,
  sequence = 2
): AgentRunEvent {
  return {
    ...baseEvent,
    sequence,
    type: "match_decision_created",
    state: "match_decided",
    artifact: {
      label: "MatchDecision",
      kind: "match-decision",
      payload
    }
  };
}

function snapshotWith(events: AgentRunEvent[]): AgentRunSnapshot {
  return {
    runId: "run-md",
    state: events.at(-1)?.state ?? "completed",
    hitlState: "approval_not_required",
    events
  };
}

const showOptionsPayload: JsonValue = {
  decisionType: "SHOW_OPTIONS",
  candidates: [
    {
      capabilityId: "MM.Inventory.GetAvailability",
      parameters: { material: "DEMOA1" },
      missing: ["plant"]
    },
    {
      capabilityId: "MM.PurchaseOrder.ListOpen",
      parameters: { material: "DEMOA1" },
      missing: []
    }
  ],
  handoff: null,
  rationale: " utterance 弱匹配库存与采购订单能力，无明确主意图。"
};

const escalatePayload: JsonValue = {
  decisionType: "ESCALATE_TO_PLANNER",
  candidates: null,
  handoff: {
    reason: "multi_intent",
    matchedIntents: [
      {
        capabilityId: "MM.Inventory.GetAvailability",
        parameters: { material: "DEMOA1", plant: "5100" },
        missing: []
      },
      {
        capabilityId: "MM.PurchaseOrder.ListOpen",
        parameters: { material: "DEMOA1", days: "30" },
        missing: []
      }
    ],
    utterance: "DEMOA1 在 5100 的库存，再列出近 30 天未清采购订单",
    registrySnapshotId: "reg-snap-2026-07-25"
  },
  rationale: "多目标 utterance 命中库存与采购订单能力，需 planner 编排。"
};

const selectPayload: JsonValue = {
  decisionType: "SELECT",
  candidates: null,
  handoff: null,
  rationale: "单意图齐参。"
};

const clarifyPayload: JsonValue = {
  decisionType: "CLARIFY",
  candidates: null,
  handoff: null,
  rationale: "缺 plant 参数。"
};

const rejectPayload: JsonValue = {
  decisionType: "REJECT",
  candidates: null,
  handoff: null,
  rationale: "技术覆盖：rfcName=BAPI_*。"
};

describe("buildMatchDecisionView - 五态只读视图", () => {
  it("returns null when snapshot is null", () => {
    expect(buildMatchDecisionView(null)).toBeNull();
  });

  it("returns null when no match-decision artifact is present", () => {
    const snap: AgentRunSnapshot = {
      runId: "run-md",
      state: "completed",
      hitlState: "approval_not_required",
      events: [
        { ...baseEvent, sequence: 1, type: "run_started", state: "running" },
        { ...baseEvent, sequence: 2, type: "narrative_created", state: "narrated" }
      ]
    };
    expect(buildMatchDecisionView(snap)).toBeNull();
  });

  it("returns null when match-decision payload is malformed (missing decisionType)", () => {
    const snap = snapshotWith([
      matchDecisionEvent({ candidates: [], rationale: "x" })
    ]);
    expect(buildMatchDecisionView(snap)).toBeNull();
  });

  it("renders SHOW_OPTIONS with candidates and rationale", () => {
    const snap = snapshotWith([matchDecisionEvent(showOptionsPayload)]);
    const view = buildMatchDecisionView(snap);
    expect(view?.decisionType).toBe("SHOW_OPTIONS");
    expect(view?.candidates).toEqual([
      {
        capabilityId: "MM.Inventory.GetAvailability",
        parameters: { material: "DEMOA1" },
        missing: ["plant"]
      },
      {
        capabilityId: "MM.PurchaseOrder.ListOpen",
        parameters: { material: "DEMOA1" },
        missing: []
      }
    ]);
    expect(view?.handoff).toBeUndefined();
    expect(view?.rationale).toBe(showOptionsPayload.rationale);
  });

  it("renders ESCALATE_TO_PLANNER with handoff and rationale", () => {
    const snap = snapshotWith([matchDecisionEvent(escalatePayload)]);
    const view = buildMatchDecisionView(snap);
    expect(view?.decisionType).toBe("ESCALATE_TO_PLANNER");
    expect(view?.candidates).toBeUndefined();
    expect(view?.handoff).toEqual({
      reason: "multi_intent",
      matchedIntents: [
        {
          capabilityId: "MM.Inventory.GetAvailability",
          parameters: { material: "DEMOA1", plant: "5100" },
          missing: []
        },
        {
          capabilityId: "MM.PurchaseOrder.ListOpen",
          parameters: { material: "DEMOA1", days: "30" },
          missing: []
        }
      ],
      utterance: "DEMOA1 在 5100 的库存，再列出近 30 天未清采购订单",
      registrySnapshotId: "reg-snap-2026-07-25"
    });
    expect(view?.rationale).toBe(escalatePayload.rationale);
  });

  it("renders SELECT view (defensive: artifact carries SELECT even though SSE reuses capability_selected)", () => {
    const snap = snapshotWith([matchDecisionEvent(selectPayload)]);
    const view = buildMatchDecisionView(snap);
    expect(view?.decisionType).toBe("SELECT");
    expect(view?.candidates).toBeUndefined();
    expect(view?.handoff).toBeUndefined();
    expect(view?.rationale).toBe("单意图齐参。");
  });

  it("renders CLARIFY view (defensive)", () => {
    const snap = snapshotWith([matchDecisionEvent(clarifyPayload)]);
    const view = buildMatchDecisionView(snap);
    expect(view?.decisionType).toBe("CLARIFY");
    expect(view?.rationale).toBe("缺 plant 参数。");
  });

  it("renders REJECT view (defensive)", () => {
    const snap = snapshotWith([matchDecisionEvent(rejectPayload)]);
    const view = buildMatchDecisionView(snap);
    expect(view?.decisionType).toBe("REJECT");
    expect(view?.rationale).toBe("技术覆盖：rfcName=BAPI_*。");
  });

  it("picks the match-decision artifact even when other artifacts are present", () => {
    const snap: AgentRunSnapshot = {
      runId: "run-md",
      state: "match_decided",
      hitlState: "approval_not_required",
      events: [
        { ...baseEvent, sequence: 1, type: "run_started", state: "running" },
        {
          ...baseEvent,
          sequence: 2,
          type: "intent_parsed",
          state: "intent_parsed",
          artifact: { label: "IntentParseResult", kind: "intent", payload: { query: "x" } }
        },
        matchDecisionEvent(escalatePayload, 3)
      ]
    };
    const view = buildMatchDecisionView(snap);
    expect(view?.decisionType).toBe("ESCALATE_TO_PLANNER");
    expect(view?.handoff?.registrySnapshotId).toBe("reg-snap-2026-07-25");
  });
});

describe("buildWorkbenchViewModel - match_decision_created event integration", () => {
  it("exposes the match-decision artifact on view.artifacts.matchDecision", () => {
    const snap: AgentRunSnapshot = {
      runId: "run-md",
      state: "match_decided",
      hitlState: "approval_not_required",
      events: [
        { ...baseEvent, sequence: 1, type: "run_started", state: "running" },
        matchDecisionEvent(showOptionsPayload, 2)
      ]
    };
    const view = buildWorkbenchViewModel(snap);
    expect(view.artifacts.matchDecision?.kind).toBe("match-decision");
    expect(view.reasoningSteps.some((step) => step.label === "匹配决策")).toBe(true);
  });

  it("does not include match-decision artifact when absent (regression)", () => {
    const snap: AgentRunSnapshot = {
      runId: "run-md",
      state: "completed",
      hitlState: "approval_not_required",
      events: [
        { ...baseEvent, sequence: 1, type: "run_started", state: "running" },
        {
          ...baseEvent,
          sequence: 2,
          type: "narrative_created",
          state: "narrated",
          artifact: { label: "Chinese Narrative", kind: "narrative", payload: { text: "ok" } }
        }
      ]
    };
    const view = buildWorkbenchViewModel(snap);
    expect(view.artifacts.matchDecision).toBeUndefined();
  });
});

describe("regression: summarizeTurn / buildChatBubbleState with match_decision_created", () => {
  const matchDecisionSnapshot: AgentRunSnapshot = {
    runId: "run-md",
    state: "match_decided",
    hitlState: "approval_not_required",
    events: [
      { ...baseEvent, sequence: 1, type: "run_started", state: "running" },
      matchDecisionEvent(escalatePayload, 2),
      {
        ...baseEvent,
        sequence: 3,
        type: "narrative_created",
        state: "narrated",
        artifact: {
          label: "Chinese Narrative",
          kind: "narrative",
          payload: { text: "需要规划层介入，已转交 planner。" }
        }
      }
    ]
  };

  it("summarizeTurn reports snapshot state (match_decided) without crashing", () => {
    const turn: ChatTurn = {
      runId: "run-md",
      query: "DEMOA1 在 5100 的库存，再列出近 30 天未清采购订单",
      snapshot: matchDecisionSnapshot,
      isRunning: false
    };
    const summary = summarizeTurn(turn);
    expect(summary.state).toBe("match_decided");
    expect(summary.label.length).toBeGreaterThan(0);
  });

  it("buildChatBubbleState shows narrative body when narrative arrives after match_decision", () => {
    const turn: ChatTurn = {
      runId: "run-md",
      query: "多目标查询",
      snapshot: matchDecisionSnapshot,
      isRunning: false
    };
    const bubble = buildChatBubbleState(turn);
    expect(bubble.hasNarrative).toBe(true);
    expect(bubble.showStreaming).toBe(false);
  });

  it("buildChatBubbleState shows streaming cursor while running before narrative arrives", () => {
    const runningSnapshot: AgentRunSnapshot = {
      runId: "run-md",
      state: "match_decided",
      hitlState: "approval_not_required",
      events: [
        { ...baseEvent, sequence: 1, type: "run_started", state: "running" },
        matchDecisionEvent(showOptionsPayload, 2)
      ]
    };
    const turn: ChatTurn = {
      runId: "run-md",
      query: "歧义查询",
      snapshot: runningSnapshot,
      isRunning: true
    };
    const bubble = buildChatBubbleState(turn);
    // narrative has not arrived yet AND turn is running -> streaming cursor
    expect(bubble.showStreaming).toBe(true);
    expect(bubble.hasNarrative).toBe(false);
  });
});
