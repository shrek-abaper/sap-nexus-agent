import { describe, expect, it } from "vitest";
import type { MaterialSupplySnapshot, ReasoningFact } from "../projection/types";
import { RecommendationDecisionEngine } from "./decision-engine";
import { RuleSetRegistry } from "./rule-set-registry";
import type {
  DecisionConstraints,
  DecisionRegistrySnapshot,
  MaterialShortageRuleSet,
  RecommendationDecisionRequest,
} from "./types";

const ruleSet = {
  ruleSetId: "material-shortage-pr",
  version: "1.0.0",
  registrySnapshotId: "snapshot-1",
  inputProjection: {
    projectionId: "material-supply-snapshot",
    version: "1.0.0",
  },
  requiredConstraints: [
    "requiredQuantity",
    "targetDate",
    "purchasingGroup",
  ],
  maxProjectionAgeMs: 86_400_000,
  actionCapabilityId: "MM.PR.CreateDraft",
  strategy: "material-shortage",
} satisfies MaterialShortageRuleSet;

const availabilityFact: ReasoningFact = {
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
  factId: "po-1",
  agentTraceId: "run-1",
  traceId: "run-1",
  gatewayTraceId: "gateway-po",
  domain: "MM",
  businessObject: "PurchaseOrder",
  predicate: "purchaseOrderItem",
  value: 99,
  unit: "EA",
  deterministic: true,
  confidence: 1,
  source: {
    nodeId: "node.po",
    capabilityId: "MM.PurchaseOrder.GetList",
    factType: "PurchaseOrder",
  },
  evidence: [{ purchaseOrder: "4500001", orderQuantity: 99 }],
  material: "MAT-1",
  plant: "P1",
  asOf: "2026-08-05T00:00:00Z",
};

const registrySnapshot: DecisionRegistrySnapshot = {
  snapshotId: "snapshot-1",
  actionCapabilities: [{
    capabilityId: "MM.PR.CreateDraft",
    kind: "Action",
    status: "active",
    sideEffect: "sap_write",
    requiresApproval: true,
    approvalPolicy: "human_required",
    requiredParameters: [
      "material",
      "plant",
      "quantity",
      "unit",
      "delivery_date",
      "purchasing_group",
    ],
  }],
};

function projection(facts = [purchaseOrderFact, availabilityFact]): MaterialSupplySnapshot {
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
      {
        nodeId: "node.po",
        nodeExecutedAt: "2026-08-05T00:00:02Z",
        dataAsOf: "2026-08-05T00:00:00Z",
      },
    ],
    completeness: "complete",
    facts,
    lineage: [],
    missingFacts: [],
    failedNodes: [],
    limitations: [],
    outputHash: "projection-hash-1",
  };
}

function request(
  constraints: DecisionConstraints = {
    requiredQuantity: 10,
    targetDate: "2026-08-15",
    purchasingGroup: "601",
  },
  facts = [purchaseOrderFact, availabilityFact],
): RecommendationDecisionRequest {
  return {
    registrySnapshot,
    projection: projection(facts),
    ruleSetRef: {
      ruleSetId: "material-shortage-pr",
      version: "1.0.0",
    },
    constraints,
    evaluatedAt: "2026-08-05T01:00:00Z",
  };
}

function createEngine(): RecommendationDecisionEngine {
  const registry = new RuleSetRegistry("snapshot-1");
  registry.register(ruleSet);
  return new RecommendationDecisionEngine(registry);
}

describe("RecommendationDecisionEngine", () => {
  it("forms one replayable pending proposal from governed shortage inputs", () => {
    const plan = createEngine().decide(request());

    expect(plan).toMatchObject({
      status: "RECOMMEND",
      snapshotId: "snapshot-1",
      projectionRef: {
        projectionId: "material-supply-snapshot",
        version: "1.0.0",
        outputHash: "projection-hash-1",
      },
      ruleSetRefs: ["material-shortage-pr@1.0.0"],
      facts: [
        expect.objectContaining({ factId: "inventory-1", value: 7, unit: "EA" }),
        expect.objectContaining({ factId: "po-1", value: 99, unit: "EA" }),
      ],
      rules: [{
        ruleId: "material-shortage",
        ruleSetRef: "material-shortage-pr@1.0.0",
        triggered: true,
      }],
      assumptions: [],
      limitations: [],
      rejectedAlternatives: [{
        code: "PO_QUANTITY_NOT_CONFIRMED_SUPPLY",
        reason: "Purchase-order quantity lacks delivery, open-quantity, and receipt-state semantics.",
        factIds: ["po-1"],
      }],
      actionProposal: {
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
        factsUsed: ["inventory-1"],
        ruleSetRefs: ["material-shortage-pr@1.0.0"],
      },
    });
    expect(Object.keys(plan.actionProposal?.parameterSources ?? {}).sort()).toEqual([
      "delivery_date",
      "material",
      "plant",
      "purchasing_group",
      "quantity",
      "unit",
    ]);
    expect(plan.actionProposal?.parameterSources.quantity).toEqual([
      { kind: "constraint", ref: "requiredQuantity" },
      { kind: "fact", ref: "inventory-1", field: "value" },
      { kind: "rule", ref: "material-shortage-pr@1.0.0" },
    ]);
    expect(plan.recommendationId).toMatch(/^rec_[a-f0-9]{24}$/);
    expect(plan.planHash).toMatch(/^[a-f0-9]{64}$/);
    expect(plan.actionProposal?.proposalId).toMatch(/^proposal_[a-f0-9]{24}$/);
    expect(plan.actionProposal?.proposalHash).toMatch(/^[a-f0-9]{64}$/);
  });

  it("replays identically when facts arrive in a different order", () => {
    const engine = createEngine();

    expect(engine.decide(request(undefined, [availabilityFact, purchaseOrderFact])))
      .toEqual(engine.decide(request(undefined, [purchaseOrderFact, availabilityFact])));
  });

  it("keeps colliding display tuples distinct in refs and hashes", () => {
    const registry = new RuleSetRegistry("snapshot-1");
    registry.register({ ...ruleSet, ruleSetId: "a@b", version: "c" });
    registry.register({ ...ruleSet, ruleSetId: "a", version: "b@c" });
    const engine = new RecommendationDecisionEngine(registry);

    const left = engine.decide({
      ...request(),
      ruleSetRef: { ruleSetId: "a@b", version: "c" },
    });
    const right = engine.decide({
      ...request(),
      ruleSetRef: { ruleSetId: "a", version: "b@c" },
    });

    expect(left.ruleSetRefs).not.toEqual(right.ruleSetRefs);
    expect(left.actionProposal?.proposalHash).not.toBe(right.actionProposal?.proposalHash);
    expect(left.planHash).not.toBe(right.planHash);
  });

  it("returns no action when available stock satisfies demand", () => {
    const plan = createEngine().decide(request({
      requiredQuantity: 7,
      targetDate: "2026-08-15",
      purchasingGroup: "601",
    }));

    expect(plan.status).toBe("NO_ACTION");
    expect(plan.rules).toEqual([{
      ruleId: "material-shortage",
      ruleSetRef: "material-shortage-pr@1.0.0",
      triggered: false,
    }]);
    expect(plan.actionProposal).toBeUndefined();
  });

  it("does not deduct purchase-order quantity from the shortage", () => {
    const plan = createEngine().decide(request());

    expect(plan.actionProposal?.parameters.quantity).toBe(3);
    expect(plan.rejectedAlternatives).toContainEqual(expect.objectContaining({
      code: "PO_QUANTITY_NOT_CONFIRMED_SUPPLY",
      factIds: ["po-1"],
    }));
  });

  it.each([
    ["requiredQuantity", "MISSING_CONSTRAINT_REQUIRED_QUANTITY"],
    ["targetDate", "MISSING_CONSTRAINT_TARGET_DATE"],
    ["purchasingGroup", "MISSING_CONSTRAINT_PURCHASING_GROUP"],
  ] as const)("clarifies a missing %s without guessing", (field, code) => {
    const constraints: DecisionConstraints = {
      requiredQuantity: 10,
      targetDate: "2026-08-15",
      purchasingGroup: "601",
    };
    delete constraints[field];

    const plan = createEngine().decide(request(constraints));

    expect(plan.status).toBe("CLARIFY");
    expect(plan.limitations).toContainEqual(expect.objectContaining({ code }));
    expect(plan.actionProposal).toBeUndefined();
  });

  it.each(["partial", "incomplete"] as const)(
    "blocks a %s projection and preserves projection evidence",
    (completeness) => {
      const input = request();
      input.projection.completeness = completeness;
      input.projection.limitations = [{ kind: "missing_optional", detail: "PurchaseOrder" }];
      input.projection.missingFacts = [{ factType: "PurchaseOrder", reason: "missing_optional" }];

      const plan = createEngine().decide(input);

      expect(plan.status).toBe("INSUFFICIENT_INPUT");
      expect(plan.limitations).toContainEqual({
        code: "PROJECTION_NOT_COMPLETE",
        detail: completeness,
        sourceRefs: ["projection:limitation:missing_optional:PurchaseOrder", "projection:missing:PurchaseOrder:missing_optional"],
      });
      expect(plan.actionProposal).toBeUndefined();
    },
  );

  it.each([
    {
      label: "stale",
      asOf: "2026-08-05T00:00:00Z",
      evaluatedAt: "2026-08-06T00:00:00.001Z",
      code: "PROJECTION_STALE",
    },
    {
      label: "invalid projection time",
      asOf: "not-a-time",
      evaluatedAt: "2026-08-05T01:00:00Z",
      code: "PROJECTION_TIME_INVALID",
    },
    {
      label: "future projection time",
      asOf: "2026-08-05T02:00:00Z",
      evaluatedAt: "2026-08-05T01:00:00Z",
      code: "PROJECTION_TIME_INVALID",
    },
    {
      label: "impossible projection calendar date",
      asOf: "2026-02-30T00:00:00Z",
      evaluatedAt: "2026-03-02T01:00:00Z",
      code: "PROJECTION_TIME_INVALID",
    },
  ])("blocks a $label", ({ asOf, evaluatedAt, code }) => {
    const input = request();
    input.projection.asOf = asOf;
    input.evaluatedAt = evaluatedAt;

    const plan = createEngine().decide(input);

    expect(plan.status).toBe("INSUFFICIENT_INPUT");
    expect(plan.limitations).toContainEqual(expect.objectContaining({ code }));
    expect(plan.actionProposal).toBeUndefined();
  });

  it("returns a structured plan for an unknown RuleSet", () => {
    const input = request();
    input.ruleSetRef = { ruleSetId: "unknown", version: "1.0.0" };

    const plan = createEngine().decide(input);

    expect(plan.status).toBe("INSUFFICIENT_INPUT");
    expect(plan.ruleSetRefs).toEqual(["unknown@1.0.0"]);
    expect(plan.limitations).toContainEqual(expect.objectContaining({
      code: "RULESET_NOT_REGISTERED",
    }));
    expect(plan.actionProposal).toBeUndefined();
  });

  it("blocks a request snapshot that differs from the bound RuleSet registry", () => {
    const input = request();
    input.registrySnapshot = { ...registrySnapshot, snapshotId: "snapshot-2" };

    const plan = createEngine().decide(input);

    expect(plan.status).toBe("INSUFFICIENT_INPUT");
    expect(plan.limitations).toContainEqual(expect.objectContaining({
      code: "SNAPSHOT_MISMATCH",
    }));
    expect(plan.actionProposal).toBeUndefined();
  });

  it("blocks an unexpected projection id or version", () => {
    const input = request();
    input.projection.projectionVersion = "2.0.0";

    const plan = createEngine().decide(input);

    expect(plan.status).toBe("INSUFFICIENT_INPUT");
    expect(plan.limitations).toContainEqual(expect.objectContaining({
      code: "PROJECTION_VERSION_MISMATCH",
    }));
  });

  it.each([
    {
      label: "unregistered",
      actionCapabilities: [],
    },
    {
      label: "inactive",
      actionCapabilities: [{
        ...registrySnapshot.actionCapabilities[0],
        status: "inactive",
      }],
    },
    {
      label: "wrong kind",
      actionCapabilities: [{
        ...registrySnapshot.actionCapabilities[0],
        kind: "Function" as const,
      }],
    },
    {
      label: "missing parameter declaration",
      actionCapabilities: [{
        ...registrySnapshot.actionCapabilities[0],
        requiredParameters: ["material", "plant", "quantity"],
      }],
    },
    {
      label: "non-write side effect",
      actionCapabilities: [{
        ...registrySnapshot.actionCapabilities[0],
        sideEffect: "none" as const,
      }],
    },
    {
      label: "missing approval requirement",
      actionCapabilities: [{
        ...registrySnapshot.actionCapabilities[0],
        requiresApproval: false,
      }],
    },
    {
      label: "non-human approval policy",
      actionCapabilities: [{
        ...registrySnapshot.actionCapabilities[0],
        approvalPolicy: "not_required" as const,
      }],
    },
    {
      label: "ambiguous duplicate",
      actionCapabilities: [
        registrySnapshot.actionCapabilities[0],
        { ...registrySnapshot.actionCapabilities[0], status: "inactive" },
      ],
    },
    {
      label: "extra required parameter",
      actionCapabilities: [{
        ...registrySnapshot.actionCapabilities[0],
        requiredParameters: [
          ...registrySnapshot.actionCapabilities[0].requiredParameters,
          "account_assignment",
        ],
      }],
    },
  ])("blocks an $label Action capability", ({ actionCapabilities }) => {
    const input = request();
    input.registrySnapshot = { ...registrySnapshot, actionCapabilities };

    const plan = createEngine().decide(input);

    expect(plan.status).toBe("INSUFFICIENT_INPUT");
    expect(plan.limitations).toContainEqual(expect.objectContaining({
      code: "ACTION_CAPABILITY_UNSUPPORTED",
    }));
    expect(plan.actionProposal).toBeUndefined();
  });

  it("blocks multiple availability facts instead of choosing one", () => {
    const secondAvailability = {
      ...availabilityFact,
      factId: "inventory-2",
      value: 8,
    };

    const plan = createEngine().decide(request(undefined, [
      purchaseOrderFact,
      availabilityFact,
      secondAvailability,
    ]));

    expect(plan.status).toBe("INSUFFICIENT_INPUT");
    expect(plan.limitations).toContainEqual({
      code: "AVAILABILITY_FACT_AMBIGUOUS",
      detail: "expected one availability fact, found 2",
      sourceRefs: ["inventory-1", "inventory-2"],
    });
    expect(plan.actionProposal).toBeUndefined();
  });

  it.each([
    ["null quantity", { value: null }, "AVAILABILITY_FACT_INVALID"],
    ["negative quantity", { value: -1 }, "AVAILABILITY_FACT_INVALID"],
    ["missing unit", { unit: null }, "AVAILABILITY_FACT_INVALID"],
    ["conflict marker", { conflict: true }, "AVAILABILITY_FACT_INVALID"],
  ] as const)("blocks an availability fact with %s", (_label, overrides, code) => {
    const invalidFact = { ...availabilityFact, ...overrides } as ReasoningFact;

    const plan = createEngine().decide(request(undefined, [invalidFact]));

    expect(plan.status).toBe("INSUFFICIENT_INPUT");
    expect(plan.limitations).toContainEqual(expect.objectContaining({ code }));
    expect(plan.actionProposal).toBeUndefined();
  });

  it.each([
    [
      "required quantity",
      { requiredQuantity: 0, targetDate: "2026-08-15", purchasingGroup: "601" },
      "CONSTRAINT_INVALID_REQUIRED_QUANTITY",
    ],
    [
      "target date",
      { requiredQuantity: 10, targetDate: "2026-02-30", purchasingGroup: "601" },
      "CONSTRAINT_INVALID_TARGET_DATE",
    ],
    [
      "purchasing group",
      { requiredQuantity: 10, targetDate: "2026-08-15", purchasingGroup: "1234" },
      "CONSTRAINT_INVALID_PURCHASING_GROUP",
    ],
  ] as const)("blocks an invalid %s", (_label, constraints, code) => {
    const plan = createEngine().decide(request(constraints));

    expect(plan.status).toBe("INSUFFICIENT_INPUT");
    expect(plan.limitations).toContainEqual(expect.objectContaining({ code }));
    expect(plan.actionProposal).toBeUndefined();
  });
});
