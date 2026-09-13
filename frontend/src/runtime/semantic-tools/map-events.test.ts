import { describe, expect, it } from "vitest";
import type { JsonValue } from "../../shared/types/artifacts";
import type { AgentRunEvent } from "../run-event-schema";
import { mapDiagnoseEvents } from "./map-events";

const baseEvent = {
  runId: "run-1",
  traceId: "trace-run-1",
  timestamp: "2026-09-11T00:00:00.000Z",
  snapshotId: "snap-1",
};

function evidenceEvent(
  type: AgentRunEvent["type"],
  state: AgentRunEvent["state"],
  ref: string,
  data: JsonValue,
  sequence: number,
  evidenceRefs: string[] = [],
): AgentRunEvent {
  return {
    ...baseEvent,
    type,
    state,
    sequence,
    objectRefs: [{ kind: type.replace(/_completed|_emitted/g, ""), ref }],
    artifact: {
      label: type,
      kind: "projection",
      payload: { ref, snapshotId: "snap-1", evidenceRefs, data },
    },
  };
}

describe("mapDiagnoseEvents", () => {
  it("maps a complete composition run to a complete diagnosis response", () => {
    const events: AgentRunEvent[] = [
      { ...baseEvent, type: "run_started", state: "running", sequence: 1 },
      evidenceEvent("plan_node_state", "running", "node:inv", {
        nodeId: "node:inv",
        capabilityId: "MM.Inventory.GetAvailability",
        state: "succeeded",
      }, 2, ["fact:inv-1"]),
      evidenceEvent("plan_node_state", "running", "node:po", {
        nodeId: "node:po",
        capabilityId: "MM.PurchaseOrder.GetList",
        state: "succeeded",
      }, 3, ["fact:po-1"]),
      evidenceTaskFact("fact:inv-1", 4, { value: 42, unit: "KG", material: "A100", plant: "1000", asOf: "2026-09-11T08:00:00Z" }),
      evidenceTaskFact("fact:po-1", 5, { value: 100, unit: "KG", material: "A100", plant: "1000", asOf: "2026-09-11T08:00:00Z" }),
      evidenceEvent("projection_completed", "running", "projection:hash-1", {
        outputHash: "hash-1",
        asOf: "2026-09-11T08:00:00Z",
        completeness: "complete",
        limitations: [],
      }, 6),
      evidenceEvent("narrative_completed", "narrated", "narrative:rec-1", {
        summary: "A100 在 1000 工厂可用 42 KG，在途 100 KG",
        limitations: [],
        evidenceRefs: ["fact:inv-1", "fact:po-1"],
      }, 7),
      { ...baseEvent, type: "run_completed", state: "completed", sequence: 8 },
    ];

    const response = mapDiagnoseEvents(events, "run-1");
    expect(response.status).toBe("complete");
    expect(response.capabilityChain).toEqual([
      { capabilityId: "MM.Inventory.GetAvailability", state: "succeeded", factRefs: ["node:inv", "fact:inv-1"] },
      { capabilityId: "MM.PurchaseOrder.GetList", state: "succeeded", factRefs: ["node:po", "fact:po-1"] },
    ]);
    expect(response.facts).toHaveLength(2);
    expect(response.facts[0]).toMatchObject({ ref: "fact:inv-1", value: 42, material: "A100", plant: "1000" });
    expect(response.resolved.semanticValues).toContainEqual({ type: "Plant", value: "1000", provenance: "fact:inv-1" });
    expect(response.narrative.summary).toContain("42 KG");
    expect(response.projection?.completeness).toBe("complete");
    expect(response.traceId).toBe("trace-run-1");
  });

  it("maps partial projection to partial status with limitations", () => {
    const events: AgentRunEvent[] = [
      evidenceEvent("projection_completed", "running", "projection:h", {
        outputHash: "h",
        asOf: "2026-09-11T08:00:00Z",
        completeness: "partial",
        limitations: [{ kind: "missing_optional", detail: "PO fact missing" }],
      }, 1),
      evidenceEvent("narrative_completed", "narrated", "narrative:r", {
        summary: "部分数据",
        limitations: [],
      }, 2),
      { ...baseEvent, type: "run_completed", state: "completed", sequence: 3 },
    ];
    const response = mapDiagnoseEvents(events, "run-1");
    expect(response.status).toBe("partial");
    expect(response.limitations).toContain("missing_optional: PO fact missing");
  });

  it("maps an incomplete projection to unavailable", () => {
    const events: AgentRunEvent[] = [
      evidenceEvent("projection_completed", "running", "projection:h", {
        outputHash: "h",
        asOf: "2026-09-11T08:00:00Z",
        completeness: "incomplete",
        limitations: [],
      }, 1),
      evidenceEvent("narrative_completed", "narrated", "narrative:r", { summary: "不可用", limitations: [] }, 2),
      { ...baseEvent, type: "run_completed", state: "completed", sequence: 3 },
    ];
    const response = mapDiagnoseEvents(events, "run-1");
    expect(response.status).toBe("unavailable");
    expect(response.error?.errorType).toBe("SEMANTIC_TOOL_UNAVAILABLE");
  });

  it("maps a write proposal to out_of_scope before execution", () => {
    const events: AgentRunEvent[] = [
      evidenceEvent("action_proposed", "running", "proposal:p1", {
        proposalId: "p1",
        capabilityId: "MM.PR.CreateDraft",
      }, 1),
      { ...baseEvent, type: "run_completed", state: "awaiting_approval", hitlState: "awaiting_human_approval", sequence: 2 },
    ];
    const response = mapDiagnoseEvents(events, "run-1");
    expect(response.status).toBe("out_of_scope");
    expect(response.capabilityChain).toEqual([]);
    expect(response.error).toBeUndefined();
  });

  it("maps a failed run to failed with error payload", () => {
    const events: AgentRunEvent[] = [
      {
        ...baseEvent,
        type: "run_failed",
        state: "failed",
        sequence: 2,
        error: { errorType: "GATEWAY_UNAVAILABLE", message: "connect refused", stage: "executing" },
      },
    ];
    const response = mapDiagnoseEvents(events, "run-1");
    expect(response.status).toBe("failed");
    expect(response.error).toEqual({ errorType: "GATEWAY_UNAVAILABLE", message: "connect refused" });
  });

  it("maps a settled run without facts to clarification", () => {
    const events: AgentRunEvent[] = [
      evidenceEvent("narrative_created", "narrated", "narrative:x", { text: "请提供物料编号" }, 1),
      { ...baseEvent, type: "run_completed", state: "completed", sequence: 2 },
    ];
    const response = mapDiagnoseEvents(events, "run-1");
    expect(response.status).toBe("clarification");
    expect(response.narrative.summary).toBe("请提供物料编号");
  });

  it("maps a legacy single-SELECT run with reasoning_fact_created", () => {
    const events: AgentRunEvent[] = [
      {
        ...baseEvent,
        type: "gateway_execute_completed",
        state: "executing",
        sequence: 2,
        capabilityId: "MM.Inventory.GetAvailability",
      },
      {
        ...baseEvent,
        type: "reasoning_fact_created",
        state: "fact_created",
        sequence: 3,
        objectRefs: [{ kind: "fact", ref: "fact:legacy-1" }],
        artifact: {
          label: "ReasoningFact",
          kind: "reasoning-fact",
          payload: { factId: "legacy-1", value: 7, unit: "EA", material: "B200", plant: "1000", asOf: "2026-09-11T08:00:00Z" },
        },
      },
      evidenceEvent("narrative_created", "narrated", "narrative:l", { text: "库存 7 EA" }, 4),
      { ...baseEvent, type: "run_completed", state: "completed", sequence: 5 },
    ];
    const response = mapDiagnoseEvents(events, "run-1");
    expect(response.status).toBe("complete");
    expect(response.capabilityChain).toEqual([
      { capabilityId: "MM.Inventory.GetAvailability", state: "executed" },
    ]);
    expect(response.facts[0]).toMatchObject({ ref: "fact:legacy-1", value: 7, material: "B200" });
  });
});

function evidenceTaskFact(
  ref: string,
  sequence: number,
  data: Record<string, unknown>,
): AgentRunEvent {
  return evidenceEvent("fact_emitted", "fact_created", ref, { factId: ref.slice(5), ...data }, sequence);
}

describe("replenishment proposal with deterministic gap", () => {
  it("keeps the supply fact and gap-basis narrative while awaiting approval", () => {
    const events: AgentRunEvent[] = [
      { ...baseEvent, type: "run_started", state: "running", sequence: 1 },
      evidenceTaskFact("fact:stock-1", 2, {
        factId: "fact-stock-1", value: 5, unit: "EA", material: "P1", plant: "5260",
      }),
      evidenceEvent("narrative_created", "narrated", "narrative:gap", {
        text: "目标需求量：10 EA\n当前可用库存：2 EA\n在途采购订单：3 EA\n缺口：5 EA",
      }, 3),
      { ...baseEvent, type: "run_completed", state: "awaiting_approval", sequence: 4 },
    ];

    const response = mapDiagnoseEvents(events, "run-1", "propose_replenishment");
    expect(response.status).toBe("awaiting_approval");
    expect(response.facts).toHaveLength(1);
    expect(response.facts[0]).toMatchObject({ value: 5, material: "P1" });
    expect(response.narrative.summary).toContain("缺口：5 EA");
  });

  it("reports a zero-gap run as complete with supply facts and no approval", () => {
    const events: AgentRunEvent[] = [
      { ...baseEvent, type: "run_started", state: "running", sequence: 1 },
      evidenceTaskFact("fact:stock-2", 2, {
        factId: "fact-stock-2", value: 17, unit: "EA", material: "P2", plant: "5260",
      }),
      evidenceEvent("narrative_created", "narrated", "narrative:sufficient", {
        text: "供应合计：17 EA，供应已覆盖目标需求，缺口为 0，无需补货。",
      }, 3),
      { ...baseEvent, type: "run_completed", state: "completed", sequence: 4 },
    ];

    const response = mapDiagnoseEvents(events, "run-1");
    expect(response.status).toBe("complete");
    expect(response.approval).toBeUndefined();
    expect(response.narrative.summary).toContain("无需补货");
  });
});
