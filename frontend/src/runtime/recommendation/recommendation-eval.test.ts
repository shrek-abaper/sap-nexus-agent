import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { MaterialSupplySnapshot, ReasoningFact } from "../projection/types";
import { RecommendationDecisionEngine } from "./decision-engine";
import {
  RuleSetRegistry,
  RuleSetRegistryError,
} from "./rule-set-registry";
import type {
  DecisionConstraints,
  DecisionRegistrySnapshot,
  MaterialShortageRuleSet,
  RecommendationDecisionRequest,
} from "./types";

type EvalCase = {
  id: string;
  requiredQuantity?: number;
  omitConstraint?: keyof DecisionConstraints;
  completeness?: MaterialSupplySnapshot["completeness"];
  projectionAgeMs?: number;
  ruleSetId?: string;
  snapshotId?: string;
  actionCapabilityState?: "missing" | "inactive" | "wrong-kind" | "missing-parameters";
  availabilityMode?: "missing" | "ambiguous" | "invalid-unit" | "conflict";
  conflictingRuleSet?: boolean;
  replayWithReorderedFacts?: boolean;
  expectedStatus?: "RECOMMEND" | "NO_ACTION" | "CLARIFY" | "INSUFFICIENT_INPUT";
  expectedLimitationCode?: string;
  expectedProposalQuantity?: number;
  expectedProposalCount?: 0 | 1;
  expectedRegistryError?: string;
  assertNoExecutionEvidence?: boolean;
};

type EvalFile = {
  schema: "sap-nexus.recommendation-decision-eval.v1";
  cases: EvalCase[];
};

const ruleSet: MaterialShortageRuleSet = {
  ruleSetId: "material-shortage-pr",
  version: "1.0.0",
  registrySnapshotId: "snapshot-1",
  inputProjection: {
    projectionId: "material-supply-snapshot",
    version: "1.0.0",
  },
  requiredConstraints: ["requiredQuantity", "targetDate", "purchasingGroup"],
  maxProjectionAgeMs: 86_400_000,
  actionCapabilityId: "MM.PR.CreateDraft",
  strategy: "material-shortage",
};

const availabilityFact: ReasoningFact = {
  factId: "inventory-1",
  agentTraceId: "run-eval",
  traceId: "run-eval",
  gatewayTraceId: "gateway-inventory",
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

const purchaseOrderFact: ReasoningFact = {
  ...availabilityFact,
  factId: "po-1",
  gatewayTraceId: "gateway-po",
  businessObject: "PurchaseOrder",
  predicate: "purchaseOrderItem",
  value: 99,
  source: { factType: "PurchaseOrder", nodeId: "node.po" },
  evidence: [{ purchaseOrder: "4500001", orderQuantity: 99 }],
};

const actionCapability = {
  capabilityId: "MM.PR.CreateDraft",
  kind: "Action" as const,
  status: "active",
  sideEffect: "sap_write" as const,
  requiresApproval: true,
  approvalPolicy: "human_required" as const,
  requiredParameters: [
    "material",
    "plant",
    "quantity",
    "unit",
    "delivery_date",
    "purchasing_group",
  ],
};

function evalRequest(evalCase: EvalCase): RecommendationDecisionRequest {
  const constraints: DecisionConstraints = {
    requiredQuantity: evalCase.requiredQuantity ?? 10,
    targetDate: "2026-08-15",
    purchasingGroup: "601",
  };
  if (evalCase.omitConstraint) delete constraints[evalCase.omitConstraint];

  const facts = evalCase.availabilityMode === "missing"
    ? [purchaseOrderFact]
    : evalCase.availabilityMode === "ambiguous"
      ? [
          purchaseOrderFact,
          availabilityFact,
          { ...availabilityFact, factId: "inventory-2", value: 8 },
        ]
      : evalCase.availabilityMode === "invalid-unit"
        ? [purchaseOrderFact, { ...availabilityFact, unit: null }]
        : evalCase.availabilityMode === "conflict"
          ? [purchaseOrderFact, { ...availabilityFact, conflict: true }]
        : [purchaseOrderFact, availabilityFact];

  let actionCapabilities: DecisionRegistrySnapshot["actionCapabilities"] = [actionCapability];
  if (evalCase.actionCapabilityState === "missing") actionCapabilities = [];
  if (evalCase.actionCapabilityState === "inactive") {
    actionCapabilities = [{ ...actionCapability, status: "inactive" }];
  }
  if (evalCase.actionCapabilityState === "wrong-kind") {
    actionCapabilities = [{ ...actionCapability, kind: "Function" }];
  }
  if (evalCase.actionCapabilityState === "missing-parameters") {
    actionCapabilities = [{ ...actionCapability, requiredParameters: ["material"] }];
  }

  const asOfEpoch = Date.parse("2026-08-05T00:00:00Z");
  const projectionAgeMs = evalCase.projectionAgeMs ?? 3_600_000;
  return {
    registrySnapshot: {
      snapshotId: evalCase.snapshotId ?? "snapshot-1",
      actionCapabilities,
    },
    projection: {
      projectionId: "material-supply-snapshot",
      projectionVersion: "1.0.0",
      snapshotId: "snapshot-1",
      asOf: "2026-08-05T00:00:00Z",
      sourceFreshness: [],
      completeness: evalCase.completeness ?? "complete",
      facts,
      lineage: [],
      missingFacts: evalCase.completeness === "incomplete"
        ? [{ factType: "InventoryAvailability", reason: "missing_required" }]
        : [],
      failedNodes: [],
      limitations: evalCase.completeness === "partial"
        ? [{ kind: "missing_optional", detail: "PurchaseOrder" }]
        : [],
      outputHash: "projection-eval-hash",
    },
    ruleSetRef: {
      ruleSetId: evalCase.ruleSetId ?? "material-shortage-pr",
      version: "1.0.0",
    },
    constraints,
    evaluatedAt: new Date(asOfEpoch + projectionAgeMs).toISOString(),
  };
}

function loadEvalFile(): EvalFile {
  const path = fileURLToPath(new URL(
    "../../../../evals/recommendation_decision_cases.json",
    import.meta.url,
  ));
  return JSON.parse(readFileSync(path, "utf8")) as EvalFile;
}

describe("recommendation decision Eval", () => {
  const evalFile = loadEvalFile();

  it("uses the versioned Eval contract", () => {
    expect(evalFile.schema).toBe("sap-nexus.recommendation-decision-eval.v1");
    expect(evalFile.cases.length).toBeGreaterThanOrEqual(15);
  });

  it.each(evalFile.cases)("passes $id", (evalCase) => {
    const registry = new RuleSetRegistry("snapshot-1");
    registry.register(ruleSet);

    if (evalCase.conflictingRuleSet) {
      let captured: RuleSetRegistryError | undefined;
      try {
        registry.register({ ...ruleSet, maxProjectionAgeMs: 1 });
      } catch (error) {
        captured = error as RuleSetRegistryError;
      }
      expect(captured).toBeInstanceOf(RuleSetRegistryError);
      expect(captured?.code).toBe(evalCase.expectedRegistryError);
      return;
    }

    const engine = new RecommendationDecisionEngine(registry);
    const input = evalRequest(evalCase);
    const plan = engine.decide(input);

    expect(plan.status).toBe(evalCase.expectedStatus);
    expect(plan.actionProposal ? 1 : 0).toBe(evalCase.expectedProposalCount ?? 0);
    if (evalCase.expectedLimitationCode) {
      expect(plan.limitations).toContainEqual(expect.objectContaining({
        code: evalCase.expectedLimitationCode,
      }));
    }
    if (evalCase.expectedProposalQuantity !== undefined) {
      expect(plan.actionProposal?.parameters.quantity)
        .toBe(evalCase.expectedProposalQuantity);
    }
    if (evalCase.replayWithReorderedFacts) {
      const replayInput = evalRequest(evalCase);
      replayInput.projection.facts.reverse();
      expect(engine.decide(replayInput)).toEqual(plan);
    }
    if (evalCase.assertNoExecutionEvidence) {
      expect(JSON.stringify(plan)).not.toMatch(
        /approvalId|executionResult|commitStatus|gatewayResult/,
      );
    }
  });
});
