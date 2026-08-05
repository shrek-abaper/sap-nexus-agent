import { canonicalJson, sha256Hex } from "../durable/canonical-json";
import { normalizeFacts } from "../projection/hash";
import type { ReasoningFact } from "../projection/types";
import { RuleSetRegistryError, type RuleSetRegistry } from "./rule-set-registry";
import type {
  ActionProposal,
  ActionProposalParameters,
  MaterialShortageRuleSet,
  ParameterSource,
  RecommendationDecisionRequest,
  RecommendationFact,
  RecommendationLimitation,
  RecommendationPlan,
  RejectedAlternative,
} from "./types";

const requiredActionParameters: Array<keyof ActionProposalParameters> = [
  "material",
  "plant",
  "quantity",
  "unit",
  "delivery_date",
  "purchasing_group",
];

function ruleSetRef(ruleSetId: string, version: string): string {
  return `${encodeURIComponent(ruleSetId)}@${encodeURIComponent(version)}`;
}

function projectFacts(facts: ReasoningFact[]): RecommendationFact[] {
  return normalizeFacts(facts).map((fact) => ({
    factId: fact.factId,
    predicate: fact.predicate,
    value: fact.value,
    unit: fact.unit,
    material: fact.material,
    plant: fact.plant,
    asOf: fact.asOf,
    source: fact.source,
  }));
}

function rejectedAlternatives(facts: RecommendationFact[]): RejectedAlternative[] {
  const purchaseOrderFactIds = facts
    .filter((fact) => fact.source.factType === "PurchaseOrder")
    .map((fact) => fact.factId);
  return purchaseOrderFactIds.length === 0
    ? []
    : [{
        code: "PO_QUANTITY_NOT_CONFIRMED_SUPPLY",
        reason: "Purchase-order quantity lacks delivery, open-quantity, and receipt-state semantics.",
        factIds: purchaseOrderFactIds,
      }];
}

function createProposal(
  snapshotId: string,
  projectionRef: RecommendationPlan["projectionRef"],
  capabilityId: "MM.PR.CreateDraft",
  parameters: ActionProposalParameters,
  parameterSources: Record<keyof ActionProposalParameters, ParameterSource[]>,
  factId: string,
  ruleRef: string,
): ActionProposal {
  const payload = {
    snapshotId,
    projectionRef,
    capabilityId,
    status: "pending_approval" as const,
    parameters,
    parameterSources,
    factsUsed: [factId],
    ruleSetRefs: [ruleRef],
  };
  const proposalHash = sha256Hex(canonicalJson(payload));
  return {
    proposalId: `proposal_${proposalHash.slice(0, 24)}`,
    ...payload,
    proposalHash,
  };
}

function finalizePlan(
  plan: Omit<RecommendationPlan, "recommendationId" | "planHash">,
): RecommendationPlan {
  const planHash = sha256Hex(canonicalJson(plan));
  return {
    recommendationId: `rec_${planHash.slice(0, 24)}`,
    planHash,
    ...plan,
  };
}

function planWithoutProposal(
  request: RecommendationDecisionRequest,
  ref: string,
  facts: RecommendationFact[],
  status: "CLARIFY" | "INSUFFICIENT_INPUT",
  summaryCode: string,
  limitations: RecommendationLimitation[],
  ruleSet?: MaterialShortageRuleSet,
): RecommendationPlan {
  return finalizePlan({
    status,
    summaryCode,
    snapshotId: request.registrySnapshot.snapshotId,
    projectionRef: {
      projectionId: request.projection.projectionId,
      version: request.projection.projectionVersion,
      outputHash: request.projection.outputHash,
    },
    ruleSetRefs: [ref],
    facts,
    rules: ruleSet
      ? [{ ruleId: ruleSet.strategy, ruleSetRef: ref, triggered: false }]
      : [],
    assumptions: [],
    limitations,
    rejectedAlternatives: rejectedAlternatives(facts),
  });
}

function limitation(
  code: string,
  detail: string,
  sourceRefs: string[] = [],
): RecommendationLimitation {
  return { code, detail, sourceRefs };
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year: number, month: number): number {
  return [
    31,
    isLeapYear(year) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ][month - 1] ?? 0;
}

function isTimezoneAwareInstant(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const offsetHour = match[7] === undefined ? 0 : Number(match[7]);
  const offsetMinute = match[8] === undefined ? 0 : Number(match[8]);
  return month >= 1
    && month <= 12
    && day >= 1
    && day <= daysInMonth(year, month)
    && hour <= 23
    && minute <= 59
    && second <= 59
    && offsetHour <= 23
    && offsetMinute <= 59
    && Number.isFinite(Date.parse(value));
}

function isCalendarDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function missingConstraint(
  request: RecommendationDecisionRequest,
  ruleSet: MaterialShortageRuleSet,
): RecommendationLimitation | null {
  for (const constraint of ruleSet.requiredConstraints) {
    if (request.constraints[constraint] === undefined) {
      const suffix = constraint.replace(/[A-Z]/g, (letter) => `_${letter}`).toUpperCase();
      return limitation(
        `MISSING_CONSTRAINT_${suffix}`,
        constraint,
        [`constraint:${constraint}`],
      );
    }
  }
  return null;
}

function invalidConstraint(
  request: RecommendationDecisionRequest,
): RecommendationLimitation | null {
  const { requiredQuantity, targetDate, purchasingGroup } = request.constraints;
  if (typeof requiredQuantity !== "number"
    || !Number.isFinite(requiredQuantity)
    || requiredQuantity <= 0) {
    return limitation(
      "CONSTRAINT_INVALID_REQUIRED_QUANTITY",
      "requiredQuantity must be a finite positive number",
      ["constraint:requiredQuantity"],
    );
  }
  if (typeof targetDate !== "string" || !isCalendarDate(targetDate)) {
    return limitation(
      "CONSTRAINT_INVALID_TARGET_DATE",
      "targetDate must be a valid YYYY-MM-DD calendar date",
      ["constraint:targetDate"],
    );
  }
  if (typeof purchasingGroup !== "string"
    || !/^[A-Za-z0-9]{1,3}$/.test(purchasingGroup)) {
    return limitation(
      "CONSTRAINT_INVALID_PURCHASING_GROUP",
      "purchasingGroup must contain one to three letters or digits",
      ["constraint:purchasingGroup"],
    );
  }
  return null;
}

function projectionEvidenceRefs(request: RecommendationDecisionRequest): string[] {
  return [
    ...request.projection.limitations.map((entry) =>
      `projection:limitation:${entry.kind}:${entry.detail}`),
    ...request.projection.missingFacts.map((entry) =>
      `projection:missing:${entry.factType}:${entry.reason}`),
  ].sort();
}

function availabilityFacts(request: RecommendationDecisionRequest): ReasoningFact[] {
  return request.projection.facts
    .filter((fact) => fact.source.factType === "InventoryAvailability"
      && fact.predicate === "availableQuantity")
    .sort((left, right) => left.factId < right.factId ? -1 : left.factId > right.factId ? 1 : 0);
}

function availabilityFactIsValid(fact: ReasoningFact): boolean {
  return typeof fact.value === "number"
    && Number.isFinite(fact.value)
    && fact.value >= 0
    && typeof fact.material === "string"
    && fact.material.length > 0
    && typeof fact.plant === "string"
    && fact.plant.length > 0
    && typeof fact.unit === "string"
    && fact.unit.length > 0
    && fact.unit.length <= 3
    && fact.deterministic === true
    && fact.confidence === 1
    && !("conflict" in fact && fact.conflict === true);
}

function actionCapabilityIsSupported(
  request: RecommendationDecisionRequest,
  ruleSet: MaterialShortageRuleSet,
): boolean {
  const matchingActions = request.registrySnapshot.actionCapabilities.filter(
    (candidate) => candidate.capabilityId === ruleSet.actionCapabilityId,
  );
  if (matchingActions.length !== 1) return false;

  const action = matchingActions[0];
  const declaredParameters = new Set(action.requiredParameters);
  return action.kind === "Action"
    && action.status === "active"
    && action.sideEffect === "sap_write"
    && action.requiresApproval === true
    && action.approvalPolicy === "human_required"
    && action.requiredParameters.length === requiredActionParameters.length
    && declaredParameters.size === requiredActionParameters.length
    && requiredActionParameters.every((parameter) =>
      declaredParameters.has(parameter));
}

export class RecommendationDecisionEngine {
  constructor(private readonly ruleSets: RuleSetRegistry) {}

  decide(request: RecommendationDecisionRequest): RecommendationPlan {
    const facts = projectFacts(request.projection.facts);
    const requestedRef = ruleSetRef(
      request.ruleSetRef.ruleSetId,
      request.ruleSetRef.version,
    );
    let ruleSet: MaterialShortageRuleSet;
    try {
      ruleSet = this.ruleSets.resolve(
        request.ruleSetRef.ruleSetId,
        request.ruleSetRef.version,
      );
    } catch (error) {
      if (!(error instanceof RuleSetRegistryError)) throw error;
      return planWithoutProposal(
        request,
        requestedRef,
        facts,
        "INSUFFICIENT_INPUT",
        error.code,
        [limitation(error.code, error.message, [requestedRef])],
      );
    }
    const ref = ruleSetRef(ruleSet.ruleSetId, ruleSet.version);

    const snapshotIds = [
      this.ruleSets.snapshotId,
      request.registrySnapshot.snapshotId,
      request.projection.snapshotId,
      ruleSet.registrySnapshotId,
    ];
    if (snapshotIds.some((snapshotId) => snapshotId.length === 0)
      || new Set(snapshotIds).size !== 1) {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        "SNAPSHOT_MISMATCH",
        [limitation("SNAPSHOT_MISMATCH", snapshotIds.join("|"), snapshotIds)],
        ruleSet,
      );
    }

    if (request.projection.projectionId !== ruleSet.inputProjection.projectionId
      || request.projection.projectionVersion !== ruleSet.inputProjection.version) {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        "PROJECTION_VERSION_MISMATCH",
        [limitation(
          "PROJECTION_VERSION_MISMATCH",
          `${request.projection.projectionId}@${request.projection.projectionVersion}`,
          [`projection:${request.projection.projectionId}@${request.projection.projectionVersion}`],
        )],
        ruleSet,
      );
    }

    if (request.projection.completeness !== "complete") {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        "PROJECTION_NOT_COMPLETE",
        [limitation(
          "PROJECTION_NOT_COMPLETE",
          request.projection.completeness,
          projectionEvidenceRefs(request),
        )],
        ruleSet,
      );
    }

    if (!isTimezoneAwareInstant(request.projection.asOf)
      || !isTimezoneAwareInstant(request.evaluatedAt)) {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        "PROJECTION_TIME_INVALID",
        [limitation(
          "PROJECTION_TIME_INVALID",
          `${request.projection.asOf}|${request.evaluatedAt}`,
          ["projection:asOf", "request:evaluatedAt"],
        )],
        ruleSet,
      );
    }
    const projectionAgeMs = Date.parse(request.evaluatedAt) - Date.parse(request.projection.asOf);
    if (projectionAgeMs < 0) {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        "PROJECTION_TIME_INVALID",
        [limitation(
          "PROJECTION_TIME_INVALID",
          `negative projection age: ${projectionAgeMs}`,
          ["projection:asOf", "request:evaluatedAt"],
        )],
        ruleSet,
      );
    }
    if (projectionAgeMs > ruleSet.maxProjectionAgeMs) {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        "PROJECTION_STALE",
        [limitation(
          "PROJECTION_STALE",
          `${projectionAgeMs} > ${ruleSet.maxProjectionAgeMs}`,
          ["projection:asOf", ref],
        )],
        ruleSet,
      );
    }

    const missing = missingConstraint(request, ruleSet);
    if (missing) {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "CLARIFY",
        missing.code,
        [missing],
        ruleSet,
      );
    }
    const invalid = invalidConstraint(request);
    if (invalid) {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        invalid.code,
        [invalid],
        ruleSet,
      );
    }

    const candidates = availabilityFacts(request);
    if (candidates.length !== 1) {
      const code = candidates.length === 0
        ? "AVAILABILITY_FACT_MISSING"
        : "AVAILABILITY_FACT_AMBIGUOUS";
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        code,
        [limitation(
          code,
          `expected one availability fact, found ${candidates.length}`,
          candidates.map((fact) => fact.factId),
        )],
        ruleSet,
      );
    }
    const availability = candidates[0];
    if (!availabilityFactIsValid(availability)) {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        "AVAILABILITY_FACT_INVALID",
        [limitation(
          "AVAILABILITY_FACT_INVALID",
          availability.factId,
          [availability.factId],
        )],
        ruleSet,
      );
    }

    if (!actionCapabilityIsSupported(request, ruleSet)) {
      return planWithoutProposal(
        request,
        ref,
        facts,
        "INSUFFICIENT_INPUT",
        "ACTION_CAPABILITY_UNSUPPORTED",
        [limitation(
          "ACTION_CAPABILITY_UNSUPPORTED",
          ruleSet.actionCapabilityId,
          [`capability:${ruleSet.actionCapabilityId}`],
        )],
        ruleSet,
      );
    }

    const shortage = request.constraints.requiredQuantity! - availability.value!;
    const triggered = shortage > 0;
    const parameters: ActionProposalParameters = {
      material: availability.material!,
      plant: availability.plant!,
      quantity: shortage,
      unit: availability.unit!,
      delivery_date: request.constraints.targetDate!,
      purchasing_group: request.constraints.purchasingGroup!,
    };
    const parameterSources: Record<keyof ActionProposalParameters, ParameterSource[]> = {
      material: [{ kind: "fact", ref: availability.factId, field: "material" }],
      plant: [{ kind: "fact", ref: availability.factId, field: "plant" }],
      quantity: [
        { kind: "constraint", ref: "requiredQuantity" },
        { kind: "fact", ref: availability.factId, field: "value" },
        { kind: "rule", ref },
      ],
      unit: [{ kind: "fact", ref: availability.factId, field: "unit" }],
      delivery_date: [{ kind: "constraint", ref: "targetDate" }],
      purchasing_group: [{ kind: "constraint", ref: "purchasingGroup" }],
    };
    const actionProposal = triggered
      ? createProposal(
          request.registrySnapshot.snapshotId,
          {
            projectionId: request.projection.projectionId,
            version: request.projection.projectionVersion,
            outputHash: request.projection.outputHash,
          },
          ruleSet.actionCapabilityId,
          parameters,
          parameterSources,
          availability.factId,
          ref,
        )
      : undefined;

    return finalizePlan({
      status: triggered ? "RECOMMEND" : "NO_ACTION",
      summaryCode: triggered ? "SHORTAGE_ACTION_PROPOSED" : "SUPPLY_SUFFICIENT",
      snapshotId: request.registrySnapshot.snapshotId,
      projectionRef: {
        projectionId: request.projection.projectionId,
        version: request.projection.projectionVersion,
        outputHash: request.projection.outputHash,
      },
      ruleSetRefs: [ref],
      facts,
      rules: [{ ruleId: ruleSet.strategy, ruleSetRef: ref, triggered }],
      assumptions: [],
      limitations: [],
      rejectedAlternatives: rejectedAlternatives(facts),
      ...(actionProposal ? { actionProposal } : {}),
    });
  }
}
