import { describe, expect, it } from "vitest";
import type { MaterialSupplySnapshot, ReasoningFact } from "../projection/types";
import type { RecommendationPlan } from "../recommendation/types";
import {
  NarrativeInputError,
  createNarrativeEnvelope,
  evaluateNarrativeGrounding,
  projectNarrativeInput,
} from "./narrative";
import type {
  NarrativeInputProjection,
  NarrativeModel,
  NarrativeProposalState,
  NarrativeSourceInput,
} from "./types";

const inventoryFact: ReasoningFact = {
  factId: "inventory-1",
  agentTraceId: "run-1",
  traceId: "run-1",
  gatewayTraceId: "gateway-inventory",
  domain: "MM",
  businessObject: "InventoryStock",
  predicate: "availableQuantity",
  value: 7,
  unit: "EA",
  deterministic: true,
  confidence: 1,
  source: {
    nodeId: "node.inventory",
    capabilityId: "MM.Inventory.GetAvailability",
    factType: "InventoryAvailability",
  },
  evidence: [{ field: "availableQuantity", value: 7 }],
  material: "MAT-1",
  plant: "P1",
  asOf: "2026-08-05T00:00:00Z",
};

const purchaseOrderFact: ReasoningFact = {
  ...inventoryFact,
  factId: "po-1",
  gatewayTraceId: "gateway-po",
  businessObject: "PurchaseOrder",
  predicate: "purchaseOrderItem",
  value: 99,
  source: {
    nodeId: "node.po",
    capabilityId: "MM.PurchaseOrder.GetList",
    factType: "PurchaseOrder",
  },
  evidence: [{ purchaseOrder: "4500001", orderQuantity: 99 }],
};

function snapshot(
  facts: ReasoningFact[] = [inventoryFact, purchaseOrderFact],
): MaterialSupplySnapshot {
  return {
    projectionId: "material-supply-snapshot",
    projectionVersion: "1.0.0",
    snapshotId: "snapshot-1",
    asOf: "2026-08-05T00:00:00Z",
    sourceFreshness: [
      {
        nodeId: "node.inventory",
        nodeExecutedAt: "2026-08-05T00:00:01Z",
        dataAsOf: "2026-08-05T00:00:00Z",
      },
    ],
    completeness: "complete",
    facts,
    lineage: [
      { field: "availableQuantity", factId: "inventory-1", evidence: { value: 7 } },
    ],
    missingFacts: [],
    failedNodes: [],
    limitations: [],
    outputHash: "projection-hash-1",
  };
}

function recommendation(): RecommendationPlan {
  return {
    recommendationId: "rec-1",
    planHash: "plan-hash-1",
    status: "RECOMMEND",
    summaryCode: "MATERIAL_SHORTAGE",
    snapshotId: "snapshot-1",
    projectionRef: {
      projectionId: "material-supply-snapshot",
      version: "1.0.0",
      outputHash: "projection-hash-1",
    },
    ruleSetRefs: ["material-shortage-pr@1.0.0"],
    facts: [
      {
        factId: "inventory-1",
        predicate: "availableQuantity",
        value: 7,
        unit: "EA",
        material: "MAT-1",
        plant: "P1",
        asOf: "2026-08-05T00:00:00Z",
        source: inventoryFact.source,
      },
    ],
    rules: [{
      ruleId: "material-shortage",
      ruleSetRef: "material-shortage-pr@1.0.0",
      triggered: true,
    }],
    assumptions: [],
    limitations: [],
    rejectedAlternatives: [],
    actionProposal: {
      proposalId: "proposal-1",
      snapshotId: "snapshot-1",
      projectionRef: {
        projectionId: "material-supply-snapshot",
        version: "1.0.0",
        outputHash: "projection-hash-1",
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
      factsUsed: ["inventory-1"],
      ruleSetRefs: ["material-shortage-pr@1.0.0"],
      proposalHash: "proposal-hash-1",
    },
  };
}

function sourceInput(
  proposalState: NarrativeProposalState = {
    status: "pending_approval",
    proposalId: "proposal-1",
    stateRef: "proposal-state:proposal-1:pending",
  },
): NarrativeSourceInput {
  return {
    locale: "zh-CN",
    facts: [inventoryFact, purchaseOrderFact],
    projection: snapshot(),
    recommendation: recommendation(),
    proposalState,
  };
}

function validCandidate(projection: NarrativeInputProjection): string {
  return JSON.stringify({
    schema: "sap-nexus.narrative-candidate.v1",
    claims: projection.items.map((item) => ({
      claimId: item.claimId,
      sourceRef: item.sourceRef,
      evidenceRefs: item.evidenceRefs,
      text: item.templateText.replace(/[。. ]$/u, "!"),
    })),
  });
}

describe("grounded narrative input", () => {
  it("projects only governed inputs with stable identities and ordering", () => {
    const first = projectNarrativeInput(sourceInput());
    const reordered = sourceInput();
    reordered.facts.reverse();
    reordered.projection.facts.reverse();

    expect(projectNarrativeInput(reordered)).toEqual(first);
    expect(first.items.length).toBeGreaterThan(5);
    expect(first.items.every((item) =>
      item.claimId.length > 0
      && item.sourceRef.length > 0
      && item.evidenceRefs.length > 0)).toBe(true);
    expect(first.recommendationRef).toBe("recommendation:rec-1");
    expect(first.proposalRef).toBe("proposal:proposal-1");
    expect(first.approvalState).toBe("pending_approval");
  });

  it("rejects mismatched projection and proposal references before calling the model", async () => {
    let calls = 0;
    const model: NarrativeModel = {
      generateJson: async () => {
        calls += 1;
        return "{}";
      },
    };
    const input = sourceInput();
    input.recommendation.projectionRef.outputHash = "different-hash";

    await expect(createNarrativeEnvelope(input, model))
      .rejects.toBeInstanceOf(NarrativeInputError);
    expect(calls).toBe(0);
  });
});

describe("grounded narrative generation", () => {
  it("uses a complete deterministic template envelope without a model", async () => {
    const input = sourceInput();
    const projection = projectNarrativeInput(input);
    const envelope = await createNarrativeEnvelope(input);

    expect(envelope).toMatchObject({
      templateFallbackUsed: true,
      recommendationRef: "recommendation:rec-1",
      proposalRef: "proposal:proposal-1",
      approvalState: "pending_approval",
      completeness: "complete",
    });
    expect(envelope.claims).toHaveLength(projection.items.length);
    expect(envelope.evidenceRefs).toEqual(
      [...new Set(envelope.claims.flatMap((claim) => claim.evidenceRefs))].sort(),
    );
    expect(envelope.summary).toContain("待审批");
    expect(evaluateNarrativeGrounding(envelope, projection)).toEqual({
      totalClaims: envelope.claims.length,
      groundedClaims: envelope.claims.length,
      unsupportedClaims: 0,
      claimGroundingRate: 1,
      unsupportedClaimRate: 0,
    });
  });

  it("accepts only a one-to-one JSON rewrite and preserves deterministic metadata", async () => {
    const input = sourceInput();
    const projection = projectNarrativeInput(input);
    let capturedPrompt = "";
    const model: NarrativeModel = {
      generateJson: async (prompt) => {
        capturedPrompt = JSON.stringify(prompt);
        return validCandidate(projection);
      },
    };

    const envelope = await createNarrativeEnvelope(input, model);

    expect(envelope.templateFallbackUsed).toBe(false);
    expect(envelope.claims.every((claim) => claim.text.endsWith("!"))).toBe(true);
    expect(envelope.limitations).toEqual(projection.limitations);
    expect(envelope.approvalState).toBe(projection.approvalState);
    expect(capturedPrompt).toContain("sap-nexus.narrative-candidate.v1");
    expect(capturedPrompt).not.toMatch(/rawGatewayPayload|conversationText|password|secret/);
  });

  it.each([
    ["invalid JSON", "not-json"],
    ["empty JSON", ""],
    ["unknown claim", "unknown-claim"],
    ["unknown evidence", "unknown-evidence"],
    ["missing claim", "missing-claim"],
    ["duplicate claim", "duplicate-claim"],
  ])("falls back for %s without retaining model text", async (_name, mode) => {
    const input = sourceInput();
    const projection = projectNarrativeInput(input);
    const template = await createNarrativeEnvelope(input);
    const candidate = JSON.parse(validCandidate(projection)) as {
      schema: string;
      claims: Array<{
        claimId: string;
        sourceRef: string;
        evidenceRefs: string[];
        text: string;
      }>;
    };
    let output = mode === "invalid JSON" ? "not-json" : "";
    if (mode === "unknown-claim") {
      candidate.claims.push({
        claimId: "claim:unsupported",
        sourceRef: "source:unsupported",
        evidenceRefs: ["evidence:unsupported"],
        text: "MODEL_UNSUPPORTED_TEXT",
      });
      output = JSON.stringify(candidate);
    }
    if (mode === "unknown-evidence") {
      candidate.claims[0].evidenceRefs = ["evidence:unsupported"];
      candidate.claims[0].text = "MODEL_UNSUPPORTED_TEXT";
      output = JSON.stringify(candidate);
    }
    if (mode === "missing-claim") {
      candidate.claims.pop();
      output = JSON.stringify(candidate);
    }
    if (mode === "duplicate-claim") {
      candidate.claims.push(candidate.claims[0]);
      output = JSON.stringify(candidate);
    }
    const model: NarrativeModel = { generateJson: async () => output };

    const result = await createNarrativeEnvelope(input, model);

    expect(result).toEqual(template);
    expect(JSON.stringify(result)).not.toContain("MODEL_UNSUPPORTED_TEXT");
  });

  it("falls back when the model is unavailable and leaves inputs immutable", async () => {
    const input = sourceInput();
    const before = structuredClone(input);
    const model: NarrativeModel = {
      generateJson: async () => {
        throw new Error("model unavailable");
      },
    };

    const result = await createNarrativeEnvelope(input, model);

    expect(result.templateFallbackUsed).toBe(true);
    expect(input).toEqual(before);
  });

  it.each([
    ["fact quantity", "fact:", "7", "999"],
    ["proposal state", "proposal-state:", "待审批", "已批准并已执行"],
  ])("rejects a reference-preserving rewrite that changes %s", async (
    _name,
    sourcePrefix,
    expectedText,
    unsupportedText,
  ) => {
    const input = sourceInput();
    const projection = projectNarrativeInput(input);
    const candidate = JSON.parse(validCandidate(projection)) as {
      claims: Array<{ sourceRef: string; text: string }>;
    };
    const changed = candidate.claims.find((claim) =>
      claim.sourceRef.startsWith(sourcePrefix) && claim.text.includes(expectedText));
    if (!changed) throw new Error("test fixture did not find target claim");
    changed.text = changed.text.replace(expectedText, unsupportedText);

    const result = await createNarrativeEnvelope(input, {
      generateJson: async () => JSON.stringify({
        schema: "sap-nexus.narrative-candidate.v1",
        claims: candidate.claims,
      }),
    });

    expect(result).toEqual(await createNarrativeEnvelope(input));
  });

  it.each([
    ["decimal point", "value", 1.5, "1.5", "15"],
    ["negative sign", "value", -1, "-1", "1"],
    ["hyphenated material", "material", "MAT-1", "MAT-1", "MAT1"],
    ["spaced material", "material", "MAT 1", "MAT 1", "MAT1"],
  ] as const)("preserves business punctuation in %s", async (
    _name,
    field,
    value,
    expectedText,
    unsupportedText,
  ) => {
    const input = structuredClone(sourceInput());
    const factIndex = input.facts.findIndex((entry) => entry.factId === "inventory-1");
    const projectionIndex = input.projection.facts.findIndex((entry) =>
      entry.factId === "inventory-1");
    if (field === "value") {
      input.facts[factIndex].value = value as number;
      input.projection.facts[projectionIndex].value = value as number;
    } else {
      input.facts[factIndex].material = value as string;
      input.projection.facts[projectionIndex].material = value as string;
    }
    const projection = projectNarrativeInput(input);
    const candidate = JSON.parse(validCandidate(projection)) as {
      claims: Array<{ sourceRef: string; text: string }>;
    };
    const changed = candidate.claims.find((claim) =>
      claim.sourceRef === "fact:inventory-1" && claim.text.includes(expectedText));
    if (!changed) throw new Error("test fixture did not find punctuated business value");
    changed.text = changed.text.replace(expectedText, unsupportedText);

    const result = await createNarrativeEnvelope(input, {
      generateJson: async () => JSON.stringify({
        schema: "sap-nexus.narrative-candidate.v1",
        claims: candidate.claims,
      }),
    });

    expect(result).toEqual(await createNarrativeEnvelope(input));
  });

  it("rejects a partial-to-complete rewrite with unchanged references", async () => {
    const input = sourceInput();
    input.projection.completeness = "partial";
    const projection = projectNarrativeInput(input);
    const candidate = JSON.parse(validCandidate(projection)) as {
      claims: Array<{ sourceRef: string; text: string }>;
    };
    const completeness = candidate.claims.find((claim) =>
      claim.sourceRef.endsWith(":completeness"));
    if (!completeness) throw new Error("test fixture did not find completeness claim");
    completeness.text = completeness.text.replace("数据部分完整", "数据完整");

    const result = await createNarrativeEnvelope(input, {
      generateJson: async () => JSON.stringify({
        schema: "sap-nexus.narrative-candidate.v1",
        claims: candidate.claims,
      }),
    });

    expect(result).toEqual(await createNarrativeEnvelope(input));
  });

  it("falls back when the model exceeds the component timeout", async () => {
    const input = sourceInput();
    const projection = projectNarrativeInput(input);
    const slowModel: NarrativeModel = {
      generateJson: async () => {
        await new Promise((resolve) => setTimeout(resolve, 30));
        return validCandidate(projection);
      },
    };

    const result = await createNarrativeEnvelope(input, slowModel, { timeoutMs: 5 });

    expect(result).toEqual(await createNarrativeEnvelope(input));
  });

  it("marks missing, duplicate, and empty claim sets as unsupported", async () => {
    const input = sourceInput();
    const projection = projectNarrativeInput(input);
    const envelope = await createNarrativeEnvelope(input);
    const missing = { ...envelope, claims: envelope.claims.slice(1) };
    const duplicate = { ...envelope, claims: [...envelope.claims, envelope.claims[0]] };
    const empty = { ...envelope, claims: [] };

    expect(evaluateNarrativeGrounding(missing, projection).unsupportedClaims).toBe(1);
    expect(evaluateNarrativeGrounding(missing, projection).claimGroundingRate).toBeLessThan(1);
    expect(evaluateNarrativeGrounding(duplicate, projection).unsupportedClaims).toBe(2);
    expect(evaluateNarrativeGrounding(duplicate, projection).claimGroundingRate).toBeLessThan(1);
    expect(evaluateNarrativeGrounding(empty, projection)).toMatchObject({
      groundedClaims: 0,
      unsupportedClaims: projection.items.length,
      claimGroundingRate: 0,
      unsupportedClaimRate: 1,
    });
  });

  it("fails closed on duplicate non-fact claim identities", () => {
    const freshnessInput = sourceInput();
    freshnessInput.projection.sourceFreshness.push({
      nodeId: "node.inventory",
      nodeExecutedAt: "2026-08-05T00:00:02Z",
      dataAsOf: "2026-08-05T00:00:00Z",
    });
    expect(() => projectNarrativeInput(freshnessInput)).toThrowError(
      expect.objectContaining({ code: "NARRATIVE_CONTENT_ID_DUPLICATE" }),
    );

    const ruleInput = sourceInput();
    ruleInput.recommendation.rules.push({ ...ruleInput.recommendation.rules[0] });
    expect(() => projectNarrativeInput(ruleInput)).toThrowError(
      expect.objectContaining({ code: "NARRATIVE_CONTENT_ID_DUPLICATE" }),
    );
  });

  it.each([
    ["approved", "已批准"],
    ["executed", "已执行"],
    ["failed", "执行失败"],
  ] as const)("renders supplied %s state without creating authority", async (status, label) => {
    const envelope = await createNarrativeEnvelope(sourceInput({
      status,
      proposalId: "proposal-1",
      stateRef: `proposal-state:proposal-1:${status}`,
    }));

    expect(envelope.approvalState).toBe(status);
    expect(envelope.summary).toContain(label);
    expect(JSON.stringify(envelope)).not.toMatch(/approvalId|gatewayRequest|commitStatus/);
  });

  it("keeps partial limitations visible and does not call them complete", async () => {
    const input = sourceInput();
    input.projection.completeness = "partial";
    input.projection.limitations = [{ kind: "missing_optional", detail: "PurchaseOrder" }];
    const envelope = await createNarrativeEnvelope(input);

    expect(envelope.completeness).toBe("partial");
    expect(envelope.limitations).toContainEqual(expect.objectContaining({
      code: "PROJECTION_MISSING_OPTIONAL",
      detail: "PurchaseOrder",
    }));
    expect(envelope.summary).toContain("部分");
    expect(envelope.summary).not.toContain("数据完整");
  });

  it("uses explicit English pending wording without implying approval", async () => {
    const input = sourceInput();
    input.locale = "en";
    const envelope = await createNarrativeEnvelope(input);
    const proposalClaim = envelope.claims.find((claim) =>
      claim.sourceRef.startsWith("proposal-state:"));

    expect(proposalClaim?.text).toContain("pending approval");
    expect(proposalClaim?.text).not.toContain("approved");
    expect(proposalClaim?.text).not.toContain("executed");
  });
});
