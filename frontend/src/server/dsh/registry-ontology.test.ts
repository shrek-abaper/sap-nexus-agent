import { afterEach, describe, expect, it } from "vitest";

import {
  buildDshHandlers,
  ontologyAnalysisEnabled,
  ONTOLOGY_ANALYSIS_TOOL,
} from "./registry";
import { toolResultToModelText } from "./runtime";
import type { OntologyAnalysisToolResponse } from "./ontology-analysis-handler";

const ORIGINAL = process.env.SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED;

afterEach(() => {
  if (ORIGINAL === undefined) delete process.env.SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED;
  else process.env.SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED = ORIGINAL;
});

describe("ontology analysis flag", () => {
  it("is disabled by default and with non-1 values", () => {
    delete process.env.SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED;
    expect(ontologyAnalysisEnabled()).toBe(false);
    process.env.SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED = "true";
    expect(ontologyAnalysisEnabled()).toBe(false);
    process.env.SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED = "1";
    expect(ontologyAnalysisEnabled()).toBe(true);
  });

  it("omits the tool without the flag", () => {
    delete process.env.SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED;
    const handlers = buildDshHandlers();
    expect(handlers[ONTOLOGY_ANALYSIS_TOOL]).toBeUndefined();
    expect(Object.keys(handlers).sort()).toEqual([
      "diagnose_material_supply",
      "propose_replenishment",
      "review_customer_exposure",
      "review_vendor_exposure",
    ]);
  });

  it("registers the tool when flagged on with an injected runner", async () => {
    process.env.SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED = "1";
    const handlers = buildDshHandlers({
      ontologyRunner: async () =>
        ({
          schemaVersion: 1,
          status: "complete",
          facts: [],
          reasons: [],
          writeGatewayCalls: 0,
          notRun: [],
        }),
    });
    expect(typeof handlers[ONTOLOGY_ANALYSIS_TOOL]).toBe("function");
    const response = await handlers[ONTOLOGY_ANALYSIS_TOOL]({
      questionType: "stock-with-unit",
    });
    expect("kind" in response ? response.kind : null).toBe("ontology-analysis");
  });
});

describe("toolResultToModelText union", () => {
  it("renders ontology narrative verbatim", () => {
    const response: OntologyAnalysisToolResponse = {
      kind: "ontology-analysis",
      contractVersion: 1,
      tool: ONTOLOGY_ANALYSIS_TOOL,
      status: "semantic_gap",
      runId: "ont-1",
      facts: [],
      results: [],
      gaps: ["FIELD_NOT_ALLOWLISTED:x.deliveryDate"],
      limitations: [],
      narrative: { summary: "语义缺口：所需事实字段不存在", limitations: [] },
    };
    expect(toolResultToModelText(response)).toBe("语义缺口：所需事实字段不存在");
  });
});
