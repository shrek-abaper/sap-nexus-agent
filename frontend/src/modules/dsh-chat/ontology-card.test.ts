import { describe, expect, it } from "vitest";

import type { DshToolCall, DshOntologyToolResult as ToolResult } from "./types";
import { isOntologyResult, ontologySections } from "./ontology-card";

function ontologyResult(overrides: Partial<ToolResult> = {}): ToolResult {
  return {
    kind: "ontology-analysis",
    status: "complete",
    runId: "ont-1",
    facts: [
      {
        factTypeRef: "sapnexus:InventoryAvailabilityFact",
        fields: { availableQuantity: { value: "12.000", semanticType: "sapnexus:AvailableQuantity" } },
        unit: { field: "unit", value: "EA" },
      },
    ],
    results: [],
    gaps: [],
    limitations: [],
    narrative: { summary: "本体约束只读分析完成", limitations: [] },
    ...overrides,
  };
}

describe("isOntologyResult", () => {
  it("discriminates by kind", () => {
    expect(isOntologyResult(ontologyResult())).toBe(true);
    expect(isOntologyResult({ status: "complete", capabilityChain: [], facts: [] })).toBe(false);
    expect(isOntologyResult(undefined)).toBe(false);
  });
});

describe("ontologySections", () => {
  it("builds fact, analysis, and limitation sections", () => {
    const sections = ontologySections(
      ontologyResult({
        results: [
          {
            nodeId: "a1",
            operatorId: "group_sum",
            status: "complete",
            rows: [
              {
                groupKey: { supplier: "V72719" },
                measures: { orderQuantity: { decimal: "250", unit: "EA" } },
              },
            ],
          },
        ],
        limitations: ["MISSING_UNIT"],
        gaps: ["x"],
      }),
    );
    expect(sections.facts[0]).toContain("12.000");
    expect(sections.facts[0]).toContain("EA");
    expect(sections.analysis[0]).toContain("group_sum");
    expect(sections.analysis[0]).toContain("250");
    expect(sections.limitations).toEqual(["MISSING_UNIT"]);
  });

  it("handles empty sections without crashing", () => {
    const sections = ontologySections(
      ontologyResult({ status: "semantic_gap", facts: [], results: [] }),
    );
    expect(sections.facts).toEqual([]);
    expect(sections.analysis).toEqual([]);
  });
});

describe("ToolCallCard ontology safety", () => {
  it("an ontology call type carries the discriminated result", () => {
    const call: DshToolCall = {
      callId: "c1",
      name: "analyze_business_question",
      args: {},
      status: "completed",
      result: ontologyResult(),
    };
    expect(isOntologyResult(call.result)).toBe(true);
  });
});

describe("defensive rendering", () => {
  it("tolerates legacy/minimal ontology results missing arrays", () => {
    const minimal = {
      kind: "ontology-analysis" as const,
      status: "failed",
      runId: "x",
    } as unknown as Parameters<typeof ontologySections>[0];
    const sections = ontologySections(minimal);
    expect(sections).toEqual({ facts: [], analysis: [], limitations: [] });
    expect(isOntologyResult(minimal)).toBe(true);
  });
});
