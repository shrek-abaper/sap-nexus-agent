import { describe, expect, it } from "vitest";
import { buildWorkbenchViewModel } from "../../src/modules/agent-console/view-model";
import type { AgentRunSnapshot } from "../../src/runtime/run-event-schema";

const snapshot: AgentRunSnapshot = {
  runId: "run-1",
  state: "completed",
  hitlState: "approval_not_required",
  events: [
    {
      runId: "run-1",
      sequence: 1,
      timestamp: "2026-07-04T00:00:00.000Z",
      type: "intent_parsed",
      state: "intent_parsed",
      artifact: {
        label: "IntentParseResult",
        kind: "intent",
        payload: { query: "DEMOA1 在 1000 还有多少可用库存？", parameters: { material: "DEMOA1" } }
      }
    },
    {
      runId: "run-1",
      sequence: 2,
      timestamp: "2026-07-04T00:00:01.000Z",
      type: "capability_selected",
      state: "capability_selected",
      capabilityId: "MM.Inventory.GetAvailability",
      artifact: {
        label: "Capability Selection",
        kind: "capability",
        payload: { capabilityId: "MM.Inventory.GetAvailability", kind: "Function" }
      }
    },
    {
      runId: "run-1",
      sequence: 3,
      timestamp: "2026-07-04T00:00:02.000Z",
      type: "callplan_created",
      state: "callplan_created",
      agentTraceId: "agent-1",
      artifact: {
        label: "CallPlan",
        kind: "callplan",
        payload: { capabilityId: "MM.Inventory.GetAvailability", parameters: { material: "DEMOA1", plant: "1000" } }
      }
    },
    {
      runId: "run-1",
      sequence: 4,
      timestamp: "2026-07-04T00:00:03.000Z",
      type: "gateway_validate_completed",
      state: "validating",
      gatewayTraceId: "gw-v",
      artifact: {
        label: "Gateway Validation",
        kind: "validation",
        payload: { success: true, traceId: "gw-v" }
      }
    },
    {
      runId: "run-1",
      sequence: 5,
      timestamp: "2026-07-04T00:00:04.000Z",
      type: "gateway_execute_completed",
      state: "executing",
      gatewayTraceId: "gw-e",
      artifact: {
        label: "ExecutionResult",
        kind: "execution-result",
        payload: { success: true, data: { availableQuantity: 12, unit: "EA" } }
      }
    },
    {
      runId: "run-1",
      sequence: 6,
      timestamp: "2026-07-04T00:00:05.000Z",
      type: "reasoning_fact_created",
      state: "fact_created",
      artifact: {
        label: "ReasoningFact",
        kind: "reasoning-fact",
        payload: { predicate: "availableQuantity", value: 12, unit: "EA" }
      }
    },
    {
      runId: "run-1",
      sequence: 7,
      timestamp: "2026-07-04T00:00:06.000Z",
      type: "narrative_created",
      state: "narrated",
      artifact: {
        label: "Chinese Narrative",
        kind: "narrative",
        payload: { text: "物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。" }
      }
    },
    {
      runId: "run-1",
      sequence: 8,
      timestamp: "2026-07-04T00:00:07.000Z",
      type: "trace_linked",
      state: "trace_linked",
      agentTraceId: "agent-1",
      gatewayTraceId: "gw-e",
      artifact: {
        label: "Trace Metadata",
        kind: "trace",
        payload: { agentTraceId: "agent-1", gatewayTraceId: "gw-e" }
      }
    }
  ]
};

describe("buildWorkbenchViewModel", () => {
  it("promotes the narrative result and preserves every current artifact in detail groups", () => {
    const view = buildWorkbenchViewModel(snapshot);

    expect(view.result.title).toBe("库存查询结果");
    expect(view.result.body).toContain("DEMOA1");
    expect(view.result.tone).toBe("success");
    expect(view.reasoningSteps.map((step) => step.label)).toEqual([
      "解析业务意图",
      "选择注册能力",
      "创建 CallPlan",
      "Gateway 校验完成",
      "Gateway 执行完成",
      "生成 ReasoningFact",
      "生成中文结论",
      "绑定 Trace"
    ]);
    expect(view.detailGroups.map((group) => group.title)).toEqual([
      "意图与能力选择",
      "执行计划",
      "Gateway 执行证据",
      "事实化与叙事",
      "Trace / Audit",
      "原始产物"
    ]);
    expect(view.detailGroups.flatMap((group) => group.artifacts.map((artifact) => artifact.kind))).toEqual([
      "intent",
      "capability",
      "callplan",
      "validation",
      "execution-result",
      "reasoning-fact",
      "narrative",
      "trace",
      "intent",
      "capability",
      "callplan",
      "validation",
      "execution-result",
      "reasoning-fact",
      "narrative",
      "trace"
    ]);
  });
});
