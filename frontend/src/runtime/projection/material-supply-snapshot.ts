import { computeOutputHash, normalizeFacts } from "./hash";
import { OutputProjectionRegistry } from "./registry";
import type {
  MaterialSupplySnapshot,
  MissingFact,
  OutputProjectionDeclaration,
  ProjectionInput,
  ReasoningFact,
  SnapshotFact,
  SnapshotLimitation,
} from "./types";

const requiredFactTypes = ["InventoryAvailability"];
const optionalFactTypes = ["PurchaseOrder"];
const failedStates = new Set(["FAILED", "TIMED_OUT", "CANCELLED"]);
const lineageFields = [
  "factId",
  "agentTraceId",
  "traceId",
  "gatewayTraceId",
  "domain",
  "businessObject",
  "predicate",
  "value",
  "unit",
  "deterministic",
  "confidence",
  "source",
  "evidence",
  "material",
  "plant",
  "asOf",
];

function compareCodeUnits(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function factType(fact: ReasoningFact): string | null {
  return typeof fact.source.factType === "string" ? fact.source.factType : null;
}

function groupKey(fact: ReasoningFact): string {
  return [
    fact.businessObject,
    fact.predicate,
    fact.material ?? "",
    fact.plant ?? "",
  ].join("\u0000");
}

function groupDetail(fact: ReasoningFact): string {
  return [
    fact.businessObject,
    fact.predicate,
    fact.material ?? "",
    fact.plant ?? "",
  ].join("|");
}

function sameValueAndUnit(left: ReasoningFact, right: ReasoningFact): boolean {
  return left.value === right.value && left.unit === right.unit;
}

function distinctValues(facts: ReasoningFact[]): Array<number | null> {
  const values: Array<number | null> = [];
  for (const fact of facts) {
    if (!values.some((value) => value === fact.value)) values.push(fact.value);
  }
  return values;
}

function distinctUnits(facts: ReasoningFact[]): Array<string | null> {
  const units: Array<string | null> = [];
  for (const fact of facts) {
    if (!units.some((unit) => unit === fact.unit)) units.push(fact.unit);
  }
  return units;
}

function normalizeMissingFacts(input: ProjectionInput): MissingFact[] {
  const presentFactTypes = new Set(
    input.facts.map(factType).filter((value): value is string => value !== null),
  );
  const missingFacts = [
    ...requiredFactTypes
      .filter((type) => !presentFactTypes.has(type))
      .map((type) => ({ factType: type, reason: "missing_required" })),
    ...optionalFactTypes
      .filter((type) => !presentFactTypes.has(type))
      .map((type) => ({ factType: type, reason: "missing_optional" })),
    ...input.planExecutionRecord.missingFacts,
  ];
  const byKey = new Map<string, MissingFact>();
  for (const missingFact of missingFacts) {
    byKey.set(`${missingFact.factType}\u0000${missingFact.reason}`, missingFact);
  }
  return [...byKey.entries()]
    .sort(([left], [right]) => compareCodeUnits(left, right))
    .map(([, missingFact]) => missingFact);
}

function addLimitation(
  limitations: Map<string, SnapshotLimitation>,
  limitation: SnapshotLimitation,
): void {
  limitations.set(`${limitation.kind}\u0000${limitation.detail}`, limitation);
}

function projectFacts(
  inputFacts: ReasoningFact[],
  limitations: Map<string, SnapshotLimitation>,
): { facts: SnapshotFact[]; hasRequiredConflict: boolean; hasRequiredUnitIssue: boolean } {
  const groups = new Map<string, ReasoningFact[]>();
  for (const fact of inputFacts) {
    const key = groupKey(fact);
    const group = groups.get(key) ?? [];
    group.push(fact);
    groups.set(key, group);
  }

  const outputFacts: SnapshotFact[] = [];
  let hasRequiredConflict = false;
  let hasRequiredUnitIssue = false;

  for (const [, unsortedGroup] of [...groups.entries()].sort(([left], [right]) =>
    compareCodeUnits(left, right))) {
    const group = [...unsortedGroup].sort((left, right) =>
      compareCodeUnits(left.factId, right.factId));
    const retained: ReasoningFact[] = [];
    for (const fact of group) {
      if (!retained.some((candidate) => sameValueAndUnit(candidate, fact))) {
        retained.push(fact);
      }
    }

    const conflict = distinctValues(group).length > 1;
    const unitIncompatibility = distinctUnits(group).length > 1;
    const required = group.some((fact) => {
      const type = factType(fact);
      return type !== null && requiredFactTypes.includes(type);
    });
    const detail = groupDetail(group[0]);

    if (conflict) {
      addLimitation(limitations, { kind: "conflict", detail });
      hasRequiredConflict ||= required;
    }
    if (unitIncompatibility) {
      addLimitation(limitations, { kind: "unit_incompatibility", detail });
      hasRequiredUnitIssue ||= required;
    }
    outputFacts.push(...retained.map((fact) => conflict ? { ...fact, conflict: true } : fact));
  }

  return {
    facts: normalizeFacts(outputFacts) as SnapshotFact[],
    hasRequiredConflict,
    hasRequiredUnitIssue,
  };
}

function buildSourceFreshness(input: ProjectionInput): MaterialSupplySnapshot["sourceFreshness"] {
  const ledgerByNode = new Map(
    input.planExecutionRecord.nodeLedgerSummary.map((entry) => [entry.nodeId, entry]),
  );
  const freshnessByNode = new Map<string, MaterialSupplySnapshot["sourceFreshness"][number]>();

  for (const fact of normalizeFacts(input.facts)) {
    const nodeId = typeof fact.source.nodeId === "string" ? fact.source.nodeId : null;
    if (nodeId === null || freshnessByNode.has(nodeId)) continue;
    freshnessByNode.set(nodeId, {
      nodeId,
      nodeExecutedAt: ledgerByNode.get(nodeId)?.nodeExecutedAt ?? "",
      dataAsOf: fact.asOf,
    });
  }

  return [...freshnessByNode.values()].sort((left, right) =>
    compareCodeUnits(left.nodeId, right.nodeId));
}

function buildLineage(facts: SnapshotFact[]): MaterialSupplySnapshot["lineage"] {
  return facts.flatMap((fact) => {
    const evidence = fact.evidence[0] ?? {};
    const lineage = lineageFields.map((field) => ({ field, factId: fact.factId, evidence }));
    if (fact.conflict === true) {
      lineage.push({ field: "conflict", factId: fact.factId, evidence });
    }
    return lineage;
  });
}

function projectMaterialSupplySnapshot(input: ProjectionInput): MaterialSupplySnapshot {
  const missingFacts = normalizeMissingFacts(input);
  const limitations = new Map<string, SnapshotLimitation>();

  for (const missingFact of missingFacts) {
    if (missingFact.reason === "missing_optional") {
      addLimitation(limitations, {
        kind: "missing_optional",
        detail: missingFact.factType,
      });
    }
    if (missingFact.reason === "no_fact_builder") {
      addLimitation(limitations, {
        kind: "no_fact_builder",
        detail: missingFact.factType,
      });
    }
  }

  const projected = projectFacts(input.facts, limitations);
  const sourceFreshness = buildSourceFreshness(input);
  const distinctDataAsOf = new Set(sourceFreshness.map((entry) => entry.dataAsOf));
  if (distinctDataAsOf.size > 1) {
    addLimitation(limitations, {
      kind: "freshness_mismatch",
      detail: [...distinctDataAsOf].sort(compareCodeUnits).join("|"),
    });
  }

  const failedNodes = [...new Set(input.planExecutionRecord.nodeLedgerSummary
    .filter((entry) => failedStates.has(entry.state))
    .map((entry) => entry.nodeId))]
    .sort(compareCodeUnits);
  const sortedLimitations = [...limitations.entries()]
    .sort(([left], [right]) => compareCodeUnits(left, right))
    .map(([, limitation]) => limitation);
  const requiredMissing = requiredFactTypes.some((type) =>
    !input.facts.some((fact) => factType(fact) === type));
  const incomplete = requiredMissing
    || failedNodes.length > 0
    || projected.hasRequiredConflict
    || projected.hasRequiredUnitIssue;
  const completeness = incomplete
    ? "incomplete"
    : sortedLimitations.length > 0
      ? "partial"
      : "complete";

  return {
    projectionId: "material-supply-snapshot",
    projectionVersion: "1.0.0",
    snapshotId: input.planExecutionRecord.snapshotId,
    asOf: input.planExecutionRecord.asOf,
    sourceFreshness,
    completeness,
    facts: projected.facts,
    lineage: buildLineage(projected.facts),
    missingFacts,
    failedNodes,
    limitations: sortedLimitations,
    outputHash: computeOutputHash(input.facts, "1.0.0", input.planExecutionRecord.snapshotId),
  };
}

export const materialSupplySnapshotProjection: OutputProjectionDeclaration = {
  projectionId: "material-supply-snapshot",
  version: "1.0.0",
  requiredFactTypes,
  optionalFactTypes,
  outputSchema: "MaterialSupplySnapshot@1.0.0",
  timeBasis: "dataAsOf",
  partialPolicy: "complete-partial-incomplete",
  project: projectMaterialSupplySnapshot,
};

export function createOutputProjectionRegistry(): OutputProjectionRegistry {
  const registry = new OutputProjectionRegistry();
  registry.register(materialSupplySnapshotProjection);
  return registry;
}
