import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { MaterialSupplySnapshot, ReasoningFact } from "../projection/types";
import type { RecommendationPlan } from "../recommendation/types";
import {
  createNarrativeEnvelope,
  evaluateNarrativeGrounding,
  projectNarrativeInput,
} from "./narrative";
import type {
  NarrativeInputProjection,
  NarrativeModel,
  NarrativeProposalStatus,
  NarrativeSourceInput,
} from "./types";

type EvalCase = {
  id: string;
  locale: "zh-CN" | "en";
  completeness: MaterialSupplySnapshot["completeness"];
  recommendationStatus: RecommendationPlan["status"];
  proposalState: NarrativeProposalStatus;
  modelMode: "none" | "valid" | "invalid_json" | "unsupported_claim" | "unavailable";
  expectedFallback: boolean;
  expectedStateText: string;
};

type EvalFile = {
  schema: "sap-nexus.grounded-narrative-eval.v1";
  cases: EvalCase[];
};

const fact: ReasoningFact = {
  factId: "inventory-1",
  agentTraceId: "run-eval",
  traceId: "run-eval",
  gatewayTraceId: "gateway-eval",
  domain: "MM",
  businessObject: "InventoryStock",
  predicate: "availableQuantity",
  value: 7,
  unit: "EA",
  deterministic: true,
  confidence: 1,
  source: { factType: "InventoryAvailability", nodeId: "node.inventory" },
  evidence: [{ field: "availableQuantity", value: 7 }],
  material: "MAT-1",
  plant: "P1",
  asOf: "2026-08-05T00:00:00Z",
};

function evalInput(evalCase: EvalCase): NarrativeSourceInput {
  const hasProposal = evalCase.proposalState !== "none";
  const projection: MaterialSupplySnapshot = {
    projectionId: "material-supply-snapshot",
    projectionVersion: "1.0.0",
    snapshotId: "snapshot-eval",
    asOf: "2026-08-05T00:00:00Z",
    sourceFreshness: [{
      nodeId: "node.inventory",
      nodeExecutedAt: "2026-08-05T00:00:01Z",
      dataAsOf: "2026-08-05T00:00:00Z",
    }],
    completeness: evalCase.completeness,
    facts: [fact],
    lineage: [{ field: "availableQuantity", factId: fact.factId, evidence: { value: 7 } }],
    missingFacts: evalCase.completeness === "incomplete"
      ? [{ factType: "PurchaseOrder", reason: "missing_required" }]
      : [],
    failedNodes: [],
    limitations: evalCase.completeness === "partial"
      ? [{ kind: "missing_optional", detail: "PurchaseOrder" }]
      : [],
    outputHash: "projection-eval-hash",
  };
  const recommendation: RecommendationPlan = {
    recommendationId: `rec-${evalCase.id}`,
    planHash: `plan-${evalCase.id}`,
    status: evalCase.recommendationStatus,
    summaryCode: evalCase.recommendationStatus === "CLARIFY"
      ? "MISSING_CONSTRAINT_TARGET_DATE"
      : "MATERIAL_SHORTAGE",
    snapshotId: "snapshot-eval",
    projectionRef: {
      projectionId: projection.projectionId,
      version: projection.projectionVersion,
      outputHash: projection.outputHash,
    },
    ruleSetRefs: ["material-shortage-pr@1.0.0"],
    facts: [{
      factId: fact.factId,
      predicate: fact.predicate,
      value: fact.value,
      unit: fact.unit,
      material: fact.material,
      plant: fact.plant,
      asOf: fact.asOf,
      source: fact.source,
    }],
    rules: [{
      ruleId: "material-shortage",
      ruleSetRef: "material-shortage-pr@1.0.0",
      triggered: hasProposal,
    }],
    assumptions: [],
    limitations: evalCase.recommendationStatus === "CLARIFY"
      ? [{
          code: "MISSING_CONSTRAINT_TARGET_DATE",
          detail: "targetDate",
          sourceRefs: ["constraint:targetDate"],
        }]
      : [],
    rejectedAlternatives: [],
    actionProposal: hasProposal ? {
      proposalId: "proposal-eval",
      snapshotId: "snapshot-eval",
      projectionRef: {
        projectionId: projection.projectionId,
        version: projection.projectionVersion,
        outputHash: projection.outputHash,
      },
      capabilityId: "MM.PR.CreateDraft",
      status: "pending_approval",
      parameters: {
        material: "MAT-1",
        plant: "P1",
        quantity: 3,
        unit: "EA",
        delivery_date: "2026-08-15",
        purchasing_group: "601",
      },
      parameterSources: {
        material: [{ kind: "fact", ref: "inventory-1", field: "material" }],
        plant: [{ kind: "fact", ref: "inventory-1", field: "plant" }],
        quantity: [{ kind: "rule", ref: "material-shortage-pr@1.0.0" }],
        unit: [{ kind: "fact", ref: "inventory-1", field: "unit" }],
        delivery_date: [{ kind: "constraint", ref: "targetDate" }],
        purchasing_group: [{ kind: "constraint", ref: "purchasingGroup" }],
      },
      factsUsed: [fact.factId],
      ruleSetRefs: ["material-shortage-pr@1.0.0"],
      proposalHash: "proposal-eval-hash",
    } : undefined,
  };
  return {
    locale: evalCase.locale,
    facts: [fact],
    projection,
    recommendation,
    proposalState: {
      status: evalCase.proposalState,
      proposalId: hasProposal ? "proposal-eval" : undefined,
      stateRef: `proposal-state:${evalCase.id}:${evalCase.proposalState}`,
    },
  };
}

function modelFor(
  mode: EvalCase["modelMode"],
  projection: NarrativeInputProjection,
): NarrativeModel | undefined {
  if (mode === "none") return undefined;
  if (mode === "unavailable") {
    return { generateJson: async () => { throw new Error("unavailable"); } };
  }
  if (mode === "invalid_json") return { generateJson: async () => "invalid" };
  const candidate = {
    schema: "sap-nexus.narrative-candidate.v1",
    claims: projection.items.map((item) => ({
      claimId: item.claimId,
      sourceRef: item.sourceRef,
      evidenceRefs: item.evidenceRefs,
      text: item.templateText,
    })),
  };
  if (mode === "unsupported_claim") {
    candidate.claims.push({
      claimId: "claim:unsupported",
      sourceRef: "source:unsupported",
      evidenceRefs: ["evidence:unsupported"],
      text: "unsupported",
    });
  }
  return { generateJson: async () => JSON.stringify(candidate) };
}

function loadEvalFile(): EvalFile {
  const path = fileURLToPath(new URL(
    "../../../../evals/grounded_narrative_cases.json",
    import.meta.url,
  ));
  return JSON.parse(readFileSync(path, "utf8")) as EvalFile;
}

describe("grounded narrative Eval", () => {
  const evalFile = loadEvalFile();

  it("uses the versioned Eval contract with all required states and bad cases", () => {
    expect(evalFile.schema).toBe("sap-nexus.grounded-narrative-eval.v1");
    expect(new Set(evalFile.cases.map((entry) => entry.proposalState))).toEqual(
      new Set(["none", "pending_approval", "approved", "executed", "failed"]),
    );
    expect(new Set(evalFile.cases.map((entry) => entry.completeness))).toContain("partial");
    expect(new Set(evalFile.cases.map((entry) => entry.completeness))).toContain("incomplete");
    expect(new Set(evalFile.cases.map((entry) => entry.recommendationStatus))).toContain("CLARIFY");
    expect(new Set(evalFile.cases.map((entry) => entry.modelMode))).toEqual(
      new Set(["none", "valid", "invalid_json", "unsupported_claim", "unavailable"]),
    );
  });

  it.each(evalFile.cases)("passes $id", async (evalCase) => {
    const input = evalInput(evalCase);
    const projection = projectNarrativeInput(input);
    const envelope = await createNarrativeEnvelope(
      input,
      modelFor(evalCase.modelMode, projection),
    );
    const metrics = evaluateNarrativeGrounding(envelope, projection);

    expect(envelope.templateFallbackUsed).toBe(evalCase.expectedFallback);
    expect(envelope.summary).toContain(evalCase.expectedStateText);
    expect(metrics.claimGroundingRate).toBe(1);
    expect(metrics.unsupportedClaimRate).toBe(0);
    expect(metrics.unsupportedClaims).toBe(0);
    expect(JSON.stringify(envelope)).not.toMatch(/approvalId|gatewayResult|commitStatus/);
    if (evalCase.expectedFallback) {
      expect(await createNarrativeEnvelope(
        input,
        modelFor(evalCase.modelMode, projection),
      )).toEqual(envelope);
    }
  });
});
