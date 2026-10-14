import { describe, expect, it } from "vitest";

import {
  QUESTION_CASES,
  createOntologyAnalysisHandler,
  type OntologyEvidence,
} from "./ontology-analysis-handler";

function evidence(overrides: Partial<OntologyEvidence> = {}): OntologyEvidence {
  return {
    schemaVersion: 1,
    status: "complete",
    writeGatewayCalls: 0,
    facts: [
      {
        factTypeRef: "sapnexus:InventoryAvailabilityFact",
        fields: { availableQuantity: { value: "12.000", semanticType: "sapnexus:AvailableQuantity" } },
        unit: { field: "unit", value: "EA" },
      },
    ],
    reasons: [],
    notRun: ["SAP live", "paid model", "chat registration"],
    ...overrides,
  };
}

describe("question type map", () => {
  it("covers the closed offline cases", () => {
    expect(QUESTION_CASES["stock-with-unit"]).toBe("q1-stock-and-unit");
    expect(QUESTION_CASES["po-grouped-by-supplier"]).toBe("q2-po-group-by-supplier");
    expect(QUESTION_CASES["po-by-vendor"]).toBe("q3-supplier-filter");
    expect(QUESTION_CASES["arrivals-next-week"]).toBe("q5-arrivals-next-week");
    expect(QUESTION_CASES["stockout-certainty"]).toBe("q6-stockout-certainty");
    expect(QUESTION_CASES["create-pr"]).toBe("write-create-pr");
  });
});

describe("ontology analysis handler (injected runner)", () => {
  it("passes typed slots and returns discriminated response with narrative", async () => {
    const requests: unknown[] = [];
    const handler = createOntologyAnalysisHandler(async (request) => {
      requests.push(request);
      return evidence();
    });
    const response = await handler({
      questionType: "stock-with-unit",
      material: "DEMOA2",
      plant: "1000",
    });
    expect(response.kind).toBe("ontology-analysis");
    expect(response.tool).toBe("analyze_business_question");
    expect(response.status).toBe("complete");
    expect(requests[0]).toMatchObject({
      caseId: "q1-stock-and-unit",
      slots: { material: "DEMOA2", plant: "1000" },
      scope: { plant: "1000" },
    });
    expect(response.narrative.summary).toContain("12.000");
    expect(response.narrative.summary).toContain("离线样例数据");
  });

  it("maps semantic gaps without fabrication", async () => {
    const handler = createOntologyAnalysisHandler(async () =>
      evidence({
        status: "semantic_gap",
        facts: [],
        reasons: ["FIELD_NOT_ALLOWLISTED:sapnexus:PurchaseOrderSupplyFact.deliveryDate"],
      }),
    );
    const response = await handler({ questionType: "arrivals-next-week" });
    expect(response.status).toBe("semantic_gap");
    expect(response.narrative.summary).toContain("缺口");
    expect(response.narrative.summary).not.toContain("到货数量");
  });

  it("rejects WRITE question types", async () => {
    const handler = createOntologyAnalysisHandler(async () =>
      evidence({ status: "rejected", facts: [], reasons: ["WRITE_REJECTED"] }),
    );
    const response = await handler({ questionType: "create-pr" });
    expect(response.status).toBe("rejected");
    expect(response.narrative.summary).toContain("拒绝");
  });

  it("rejects unknown question type without invoking the runner", async () => {
    let called = false;
    const handler = createOntologyAnalysisHandler(async () => {
      called = true;
      return evidence();
    });
    const response = await handler({ questionType: "drop-tables" });
    expect(called).toBe(false);
    expect(response.status).toBe("rejected");
    expect(response.error?.errorType).toBe("INVALID_QUESTION_TYPE");
  });

  it("maps partial status and lists limitations", async () => {
    const handler = createOntologyAnalysisHandler(async () =>
      evidence({
        status: "partial",
        facts: [],
        analysis: {
          results: [
            {
              nodeId: "a1",
              operatorId: "group_sum",
              status: "partial",
              rows: [
                {
                  groupKey: { supplier: "V72719" },
                  measures: { orderQuantity: { decimal: "250", unit: "EA" } },
                },
              ],
              excludedRows: [{ factId: "r9", reason: "MISSING_UNIT" }],
            },
          ],
        },
      }),
    );
    const response = await handler({ questionType: "po-grouped-by-supplier" });
    expect(response.status).toBe("partial");
    expect(response.results[0].rows[0]).toBeTruthy();
    expect(response.limitations.join(" ")).toContain("MISSING_UNIT");
  });
});

describe.skipIf(!process.env.RUN_PYTHON_INTEGRATION)("real Python subprocess", () => {
  it("runs q1 offline through the default runner", async () => {
    const handler = createOntologyAnalysisHandler();
    const response = await handler({
      questionType: "stock-with-unit",
      material: "DEMOA2",
      plant: "1000",
    });
    expect(response.status).toBe("complete");
    expect(response.status).toBe("complete");
    expect(response.facts.length).toBeGreaterThan(0);
  });
});

describe("live model routing", () => {
  it("routes free-form question to the model interpreter when the live flag is on", async () => {
    const original = process.env.SAP_NEXUS_LLM_LIVE;
    process.env.SAP_NEXUS_LLM_LIVE = "1";
    try {
      const requests: unknown[] = [];
      const handler = createOntologyAnalysisHandler(async (request) => {
        requests.push(request);
        return evidence();
      });
      await handler({ question: "帮我查 DEMOA2 在 1000 工厂的库存，订单按供应商汇总" });
      const sent = requests[0] as { interpreter?: string; utterance?: string; slots?: Record<string, string> };
      expect(sent.interpreter).toBe("model");
      expect(sent.utterance).toContain("DEMOA2");
    } finally {
      if (original === undefined) delete process.env.SAP_NEXUS_LLM_LIVE;
      else process.env.SAP_NEXUS_LLM_LIVE = original;
    }
  });

  it("falls back to the fake questionType path without the live flag", async () => {
    const original = process.env.SAP_NEXUS_LLM_LIVE;
    delete process.env.SAP_NEXUS_LLM_LIVE;
    try {
      const requests: unknown[] = [];
      const handler = createOntologyAnalysisHandler(async (request) => {
        requests.push(request);
        return evidence();
      });
      await handler({ questionType: "stock-with-unit", material: "DEMOA2", plant: "1000" });
      const sent = requests[0] as { caseId?: string };
      expect(sent.caseId).toBe("q1-stock-and-unit");
    } finally {
      if (original !== undefined) process.env.SAP_NEXUS_LLM_LIVE = original;
    }
  });
});
