import type { AgentRunEvent } from "../run-event-schema";
import type { JsonValue, RedactedArtifact } from "../../shared/types/artifacts";
import { redactArtifact } from "../redaction";

export type PlanEvidenceObjectKind =
  | "intent"
  | "capability"
  | "plan"
  | "node"
  | "fact"
  | "projection"
  | "recommendation"
  | "narrative"
  | "proposal"
  | "approval"
  | "action";

export type PlanEvidenceObject = {
  ref: string;
  kind: PlanEvidenceObjectKind;
  snapshotId: string;
  payload: JsonValue;
  evidenceRefs?: string[];
};

export type PlanEvidenceBundle = {
  runId: string;
  traceId: string;
  snapshotId: string;
  startSequence: number;
  objects: PlanEvidenceObject[];
};

export class PlanEvidenceContractError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "PlanEvidenceContractError";
  }
}

type EventDescriptor = {
  eventType: AgentRunEvent["type"];
  state: AgentRunEvent["state"];
  artifactKind: RedactedArtifact["kind"];
  label: string;
  order: number;
};

const DESCRIPTORS: Record<PlanEvidenceObjectKind, EventDescriptor> = {
  intent: { eventType: "intent_recognized", state: "intent_parsed", artifactKind: "intent-envelope", label: "IntentEnvelope", order: 0 },
  capability: { eventType: "capability_recalled", state: "capability_selected", artifactKind: "capability-recall", label: "Capability Recall", order: 1 },
  plan: { eventType: "plan_compiled", state: "running", artifactKind: "plan-graph", label: "PlanGraph", order: 2 },
  node: { eventType: "plan_node_state", state: "running", artifactKind: "node-ledger", label: "Plan Node State", order: 3 },
  fact: { eventType: "fact_emitted", state: "fact_created", artifactKind: "fact", label: "ReasoningFact", order: 4 },
  projection: { eventType: "projection_completed", state: "running", artifactKind: "projection", label: "OutputProjection", order: 5 },
  recommendation: { eventType: "recommendation_completed", state: "running", artifactKind: "recommendation", label: "RecommendationPlan", order: 6 },
  narrative: { eventType: "narrative_completed", state: "narrated", artifactKind: "narrative-envelope", label: "NarrativeEnvelope", order: 7 },
  proposal: { eventType: "action_proposed", state: "running", artifactKind: "action-proposal", label: "ActionProposal", order: 8 },
  approval: { eventType: "approval_updated", state: "approval_checked", artifactKind: "approval-record", label: "ApprovalRecord", order: 9 },
  action: { eventType: "action_executed", state: "executing", artifactKind: "action-result", label: "ActionResult", order: 10 },
};

const FORBIDDEN_TECHNICAL_KEY = /^(rfcname|technicalbinding|bindingid|executorbinding|url|endpoint|rawsql|sql|rawsappayload|rawgatewaypayload)$/i;
const ALLOWED_PAYLOAD_KEYS: Record<PlanEvidenceObjectKind, ReadonlySet<string>> = {
  intent: new Set(["intentId", "goal", "query", "confidence", "candidates", "constraints", "entities", "source"]),
  capability: new Set(["capabilityId", "displayName", "description", "kind", "sideEffect", "requiresApproval", "status", "score", "rationale"]),
  plan: new Set(["planGraphVersion", "planId", "goalId", "executionMode", "snapshotId", "nodes", "edges", "topologicalOrder", "goalOutputs", "readPartition", "actionPartition", "projectionRef", "ruleSetRefs", "governance", "gaps"]),
  node: new Set(["nodeId", "capabilityId", "state", "attempt", "inputHash", "resultRef", "traceSpan", "updatedAt", "dependencies", "blockedBy", "safeCallPlan", "safeResult", "traceSummary", "producesFactTypes"]),
  fact: new Set(["factId", "factTypeId", "agentTraceId", "traceId", "gatewayTraceId", "domain", "businessObject", "predicate", "value", "availableQuantity", "orderQuantity", "unit", "deterministic", "confidence", "material", "plant", "asOf", "traceRef", "sourceSummary", "evidenceSummary"]),
  projection: new Set(["projectionId", "projectionVersion", "snapshotId", "asOf", "sourceFreshness", "completeness", "freshness", "facts", "lineage", "missingFacts", "failedNodes", "limitations", "outputHash"]),
  recommendation: new Set(["recommendationId", "planHash", "status", "summaryCode", "snapshotId", "projectionRef", "ruleSetRefs", "facts", "rules", "assumptions", "limitations", "rejectedAlternatives", "actionProposal"]),
  narrative: new Set(["summary", "claims", "evidenceRefs", "limitations", "recommendationRef", "proposalRef", "approvalState", "completeness", "templateFallbackUsed"]),
  proposal: new Set(["proposalId", "snapshotId", "projectionRef", "capabilityId", "status", "parameters", "parameterSources", "factsUsed", "ruleSetRefs", "proposalHash"]),
  approval: new Set(["id", "approvalId", "proposalId", "snapshotId", "status", "principalId", "parameterSnapshotHash", "proposalHash", "parameters", "expiresAt", "decidedAt", "traceId"]),
  action: new Set(["actionId", "proposalId", "approvalId", "snapshotId", "status", "capabilityId", "resultSummary", "gatewayTraceId", "traceId", "executedAt", "idempotencyKey", "executionHash"]),
};

export function projectPlanEvidenceEvents(bundle: PlanEvidenceBundle): AgentRunEvent[] {
  validateEnvelope(bundle);
  const refs = new Map<string, PlanEvidenceObject>();
  for (const object of bundle.objects) {
    if (!object.ref || refs.has(object.ref)) {
      throw new PlanEvidenceContractError("DUPLICATE_OBJECT_REFERENCE", `Object reference is empty or duplicated: ${object.ref}`);
    }
    if (object.snapshotId !== bundle.snapshotId) {
      throw new PlanEvidenceContractError("CROSS_SNAPSHOT_REFERENCE", `Object ${object.ref} is not bound to ${bundle.snapshotId}`);
    }
    assertSafePayload(object.payload, object.ref);
    assertAllowedPayload(object);
    refs.set(object.ref, object);
  }
  for (const object of bundle.objects) {
    for (const evidenceRef of governedEvidenceRefs(object)) {
      if (!refs.has(evidenceRef)) {
        throw new PlanEvidenceContractError("UNKNOWN_OBJECT_REFERENCE", `Object ${object.ref} references unknown evidence ${evidenceRef}`);
      }
    }
  }

  const ordered = [...bundle.objects].sort((left, right) => {
    const stage = DESCRIPTORS[left.kind].order - DESCRIPTORS[right.kind].order;
    return stage || compareCodeUnits(left.ref, right.ref);
  });
  const timestamp = new Date().toISOString();
  return ordered.map((object, index) => {
    const descriptor = DESCRIPTORS[object.kind];
    return {
      runId: bundle.runId,
      traceId: bundle.traceId,
      snapshotId: bundle.snapshotId,
      sequence: bundle.startSequence + index,
      timestamp,
      type: descriptor.eventType,
      state: descriptor.state,
      objectRefs: [{ kind: object.kind, ref: object.ref }],
      artifact: redactArtifact({
        label: descriptor.label,
        kind: descriptor.artifactKind,
        payload: {
          ref: object.ref,
          snapshotId: object.snapshotId,
          evidenceRefs: object.evidenceRefs ?? [],
          data: object.payload,
        },
      }),
    };
  });
}

function assertAllowedPayload(object: PlanEvidenceObject): void {
  const payload = jsonRecord(object.payload);
  if (!payload) {
    throw new PlanEvidenceContractError("INVALID_OBJECT_PAYLOAD", `Object ${object.ref} payload must be an object`);
  }
  const allowed = ALLOWED_PAYLOAD_KEYS[object.kind];
  for (const key of Object.keys(payload)) {
    if (!allowed.has(key)) {
      throw new PlanEvidenceContractError("UNSUPPORTED_FIELD", `Object ${object.ref} contains unsupported field ${key}`);
    }
  }
}

function compareCodeUnits(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function governedEvidenceRefs(object: PlanEvidenceObject): string[] {
  const refs = [...(object.evidenceRefs ?? [])];
  if (object.kind !== "narrative") return refs;

  const payload = jsonRecord(object.payload);
  if (!payload) return refs;
  refs.push(...jsonStringArray(payload.evidenceRefs));
  if (Array.isArray(payload.claims)) {
    for (const entry of payload.claims) {
      const claim = jsonRecord(entry);
      if (claim) refs.push(...jsonStringArray(claim.evidenceRefs));
    }
  }
  return refs;
}

function jsonRecord(value: unknown): Record<string, JsonValue> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, JsonValue>
    : null;
}

function jsonStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string" && entry.length > 0)
    : [];
}

function validateEnvelope(bundle: PlanEvidenceBundle): void {
  if (!bundle.runId || !bundle.traceId || !bundle.snapshotId || !Number.isInteger(bundle.startSequence) || bundle.startSequence < 1) {
    throw new PlanEvidenceContractError("INVALID_EVENT_ENVELOPE", "runId, traceId, snapshotId and a positive startSequence are required");
  }
}

function assertSafePayload(value: JsonValue, path: string): void {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => assertSafePayload(entry, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") {
    return;
  }
  for (const [key, entry] of Object.entries(value)) {
    if (FORBIDDEN_TECHNICAL_KEY.test(key)) {
      throw new PlanEvidenceContractError("UNSAFE_FIELD", `Unsafe technical field at ${path}.${key}`);
    }
    assertSafePayload(entry, `${path}.${key}`);
  }
}
