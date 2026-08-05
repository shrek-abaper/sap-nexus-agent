import type { JsonValue } from "../../shared/types/artifacts";
import type { NarrativeEnvelope } from "../narrative/types";
import type { PlanGraphV2, PlanExecutorResult } from "../plan-executor/types";
import type { PlanEvidenceObject } from "../plan-evidence/event-projector";
import type { MaterialSupplySnapshot, ReasoningFact } from "../projection/types";
import type { RecommendationPlan } from "../recommendation/types";

type CompositionEvidenceInput = {
  snapshotId: string;
  graph: PlanGraphV2;
  execution: PlanExecutorResult;
  facts: ReasoningFact[];
  projection: MaterialSupplySnapshot;
  recommendation: RecommendationPlan;
  narrative: NarrativeEnvelope;
};

export function compositionEvidenceObjects(
  input: CompositionEvidenceInput,
): PlanEvidenceObject[] {
  const objects = new Map<string, PlanEvidenceObject>();
  const add = (object: PlanEvidenceObject) => {
    if (!objects.has(object.ref)) objects.set(object.ref, object);
  };
  const object = (
    ref: string,
    kind: PlanEvidenceObject["kind"],
    payload: unknown,
    evidenceRefs: string[] = [],
  ): PlanEvidenceObject => ({
    ref,
    kind,
    snapshotId: input.snapshotId,
    payload: json(payload),
    evidenceRefs,
  });

  const factRefsByNode = new Map<string, string[]>();
  for (const fact of input.facts) {
    const ref = `fact:${fact.factId}`;
    const nodeId = typeof fact.source.nodeId === "string" ? fact.source.nodeId : "";
    if (nodeId) factRefsByNode.set(nodeId, [...(factRefsByNode.get(nodeId) ?? []), ref]);
    add(object(ref, "fact", {
      factId: fact.factId,
      agentTraceId: fact.agentTraceId,
      traceId: fact.traceId,
      gatewayTraceId: fact.gatewayTraceId,
      domain: fact.domain,
      businessObject: fact.businessObject,
      predicate: fact.predicate,
      value: fact.value,
      unit: fact.unit,
      deterministic: fact.deterministic,
      confidence: fact.confidence,
      material: fact.material,
      plant: fact.plant,
      asOf: fact.asOf,
      sourceSummary: fact.source,
      evidenceSummary: fact.evidence,
    }));
  }

  const nodeRefs = input.graph.nodes.map((node) => `node:${node.nodeId}`);
  add(object(`plan:${input.graph.planId}`, "plan", input.graph, nodeRefs));
  for (const node of input.graph.nodes) {
    const ledger = input.execution.nodeLedger[node.nodeId];
    add(object(`node:${node.nodeId}`, "node", {
      nodeId: node.nodeId,
      capabilityId: node.capabilityId,
      state: ledger?.state ?? (node.governance.requiresApproval ? "BLOCKED_APPROVAL" : "BLOCKED_DEPENDENCY"),
      attempt: ledger?.attempt ?? 0,
      inputHash: ledger?.inputHash ?? "",
      resultRef: ledger?.resultRef ?? null,
      traceSpan: ledger?.traceSpan ?? null,
      updatedAt: ledger?.updatedAt ?? "",
      dependencies: input.graph.edges.filter((edge) => edge.toNodeId === node.nodeId).map((edge) => edge.fromNodeId),
      producesFactTypes: node.producesFactTypes,
    }, factRefsByNode.get(node.nodeId) ?? []));
  }

  const factRefs = input.facts.map((fact) => `fact:${fact.factId}`);
  const projectionRef = `projection:${input.projection.outputHash}`;
  const recommendationRef = `recommendation:${input.recommendation.recommendationId}`;
  add(object(projectionRef, "projection", input.projection, factRefs));
  add(object(recommendationRef, "recommendation", input.recommendation, [projectionRef, ...factRefs]));
  if (input.recommendation.actionProposal) {
    add(object(
      `proposal:${input.recommendation.actionProposal.proposalId}`,
      "proposal",
      input.recommendation.actionProposal,
      [recommendationRef, projectionRef, ...factRefs],
    ));
  }

  const narrativeRefs = unique([
    ...input.narrative.evidenceRefs,
    ...input.narrative.claims.flatMap((claim) => claim.evidenceRefs),
  ]);
  for (const ref of narrativeRefs) {
    if (objects.has(ref)) continue;
    add(aliasObject(ref, input, object));
  }
  add(object(
    `narrative:${input.recommendation.recommendationId}`,
    "narrative",
    input.narrative,
    narrativeRefs,
  ));
  return [...objects.values()];
}

function aliasObject(
  ref: string,
  input: CompositionEvidenceInput,
  object: (ref: string, kind: PlanEvidenceObject["kind"], payload: unknown, evidenceRefs?: string[]) => PlanEvidenceObject,
): PlanEvidenceObject {
  if (ref.startsWith("fact:")) {
    return object(ref, "fact", { factId: ref.slice("fact:".length) });
  }
  if (ref.startsWith("projection:")) {
    return object(ref, "projection", {
      projectionId: input.projection.projectionId,
      projectionVersion: input.projection.projectionVersion,
      outputHash: input.projection.outputHash,
    });
  }
  if (ref.startsWith("proposal:")) {
    return object(ref, "proposal", {
      proposalId: input.recommendation.actionProposal?.proposalId ?? ref.slice("proposal:".length),
      status: input.recommendation.actionProposal?.status ?? "pending_approval",
    });
  }
  return object(ref, "recommendation", {
    recommendationId: input.recommendation.recommendationId,
    status: input.recommendation.status,
  });
}

function json(value: unknown): JsonValue {
  return JSON.parse(JSON.stringify(value)) as JsonValue;
}

function unique(values: string[]): string[] {
  return [...new Set(values)].sort();
}
