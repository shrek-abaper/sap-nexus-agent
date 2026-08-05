import type { AgentRunSnapshot } from "../../runtime/run-event-schema";
import type { JsonValue, RedactedArtifact } from "../../shared/types/artifacts";

export type PlanEvidenceSectionId =
  | "conversation"
  | "intent-recall"
  | "plan"
  | "execution"
  | "evidence"
  | "recommendation-narrative"
  | "action-approval"
  | "trace-replay";

export type PlanEvidenceObjectView = {
  ref: string;
  kind: RedactedArtifact["kind"];
  label: string;
  data: JsonValue;
  evidenceRefs: string[];
};

export type PlanEvidenceClaimView = {
  claimId: string;
  text: string;
  evidenceRefs: string[];
  evidenceTargets: PlanEvidenceObjectView[];
  supported: boolean;
};

export type PlanEvidenceView = {
  mode: "loading" | "empty" | "ready" | "limited" | "error";
  sections: Array<{ id: PlanEvidenceSectionId; label: string; objects: PlanEvidenceObjectView[] }>;
  desktopColumns: { left: PlanEvidenceSectionId; right: PlanEvidenceSectionId };
  mobileOrder: PlanEvidenceSectionId[];
  claims: PlanEvidenceClaimView[];
  limitations: string[];
  proposal: ({
    ref: string;
    status: string;
    capabilityId: string;
    proposalHash: string;
    parameters: JsonValue;
    parameterSources: JsonValue;
    factsUsed: string[];
    ruleSetRefs: string[];
    readOnly: boolean;
  } & Record<string, unknown>) | null;
  approval: (Record<string, JsonValue> & {
    approvalId: string;
    status: string;
    capabilityVersion: string;
    separationOfDutyResult: string;
  }) | null;
  canDecideApproval: boolean;
  replayMessage: string | null;
};

const SECTION_DEFINITIONS: Array<{ id: PlanEvidenceSectionId; label: string }> = [
  { id: "conversation", label: "Conversation" },
  { id: "intent-recall", label: "Intent / Recall" },
  { id: "plan", label: "Plan" },
  { id: "execution", label: "Execution" },
  { id: "evidence", label: "Evidence" },
  { id: "recommendation-narrative", label: "Recommendation / Narrative" },
  { id: "action-approval", label: "Action / Approval" },
  { id: "trace-replay", label: "Trace / Replay" },
];

const SECTION_BY_KIND: Partial<Record<RedactedArtifact["kind"], PlanEvidenceSectionId>> = {
  intent: "intent-recall",
  "intent-envelope": "intent-recall",
  capability: "intent-recall",
  "capability-recall": "intent-recall",
  "match-decision": "intent-recall",
  callplan: "plan",
  "plan-graph": "plan",
  validation: "execution",
  "execution-result": "execution",
  "node-ledger": "execution",
  "reasoning-fact": "evidence",
  fact: "evidence",
  projection: "evidence",
  recommendation: "recommendation-narrative",
  narrative: "recommendation-narrative",
  "narrative-envelope": "recommendation-narrative",
  approval: "action-approval",
  "action-proposal": "action-approval",
  "approval-record": "action-approval",
  "action-result": "action-approval",
  trace: "trace-replay",
};

export function buildPlanEvidenceView(snapshot: AgentRunSnapshot | null, loading = false): PlanEvidenceView {
  if (!snapshot) {
    return emptyView(loading ? "loading" : "empty");
  }

  const artifactObjects = snapshot.events.flatMap((event) => {
    if (!event.artifact) return [];
    return [parseArtifact(event.artifact, event.sequence)];
  });
  const objects = [...artifactObjects, traceReplayObject(snapshot)];
  const byRef = new Map(objects.map((object) => [object.ref, object]));
  const sections = SECTION_DEFINITIONS.map((definition) => ({
    ...definition,
    objects: objects.filter((object) => SECTION_BY_KIND[object.kind] === definition.id),
  }));
  const claims = objects
    .filter((object) => object.kind === "narrative-envelope")
    .flatMap((object) => parseClaims(object.data, byRef));
  const limitations = unique(objects.flatMap((object) => readLimitationDetails(object.data)));
  const proposalObject = objects.find((object) => object.kind === "action-proposal");
  const approvalObject = [...objects].reverse().find(
    (object) => object.kind === "approval" || object.kind === "approval-record",
  );
  const approvalData = approvalObject ? objectRecord(approvalObject.data) : null;
  const approval = approvalData
    ? {
        ...approvalData,
        approvalId: text(approvalData.approvalId) || text(approvalData.id),
        status: text(approvalData.status),
        capabilityVersion: text(approvalData.capabilityVersion),
        separationOfDutyResult: text(approvalData.separationOfDutyResult),
      }
    : null;
  const proposalData = proposalObject ? objectRecord(proposalObject.data) : null;
  const proposal = proposalObject && proposalData
    ? {
        ref: proposalObject.ref,
        status: text(proposalData.status),
        capabilityId: text(proposalData.capabilityId),
        proposalHash: text(proposalData.proposalHash),
        parameters: (proposalData.parameters ?? {}) as JsonValue,
        parameterSources: (proposalData.parameterSources ?? {}) as JsonValue,
        factsUsed: stringArray(proposalData.factsUsed),
        ruleSetRefs: stringArray(proposalData.ruleSetRefs),
        readOnly: approval?.status !== "pending",
      }
    : null;
  const replayStatus = snapshot.replayIntegrity?.status ?? "consistent";
  const hasUnsupportedClaim = claims.some((claim) => !claim.supported);
  const hasUnsupportedReference = objects.some((object) => object.evidenceRefs.some((ref) => !byRef.has(ref)));
  const hasPartialEvidence = objects.some(isPartialObject);
  const mode = snapshot.state === "failed" || Boolean(snapshot.error) || replayStatus === "conflict" || hasUnsupportedClaim || hasUnsupportedReference
    ? "error"
    : replayStatus === "gap" || hasPartialEvidence
      ? "limited"
      : "ready";

  return {
    mode,
    sections,
    desktopColumns: { left: "plan", right: "evidence" },
    mobileOrder: sections.map((section) => section.id),
    claims,
    limitations,
    proposal,
    approval,
    canDecideApproval: Boolean(
      approval?.approvalId
      && approval.status === "pending"
      && snapshot.hitlState === "awaiting_human_approval",
    ),
    replayMessage: snapshot.replayIntegrity?.message ?? null,
  };
}

function traceReplayObject(snapshot: AgentRunSnapshot): PlanEvidenceObjectView {
  const traceIds = unique(snapshot.events.flatMap((event) => [event.traceId, event.agentTraceId, event.gatewayTraceId]
    .filter((value): value is string => Boolean(value))));
  const snapshotIds = unique(snapshot.events.flatMap((event) => event.snapshotId ? [event.snapshotId] : []));
  return {
    ref: traceIds[0] ?? `run-${snapshot.runId}-replay`,
    kind: "trace",
    label: "Run / Trace / Replay",
    data: {
      runId: snapshot.runId,
      traceIds,
      snapshotIds,
      lastSequence: snapshot.events.at(-1)?.sequence ?? 0,
      replayStatus: snapshot.replayIntegrity?.status ?? "consistent",
    },
    evidenceRefs: [],
  };
}

function emptyView(mode: "loading" | "empty"): PlanEvidenceView {
  const sections = SECTION_DEFINITIONS.map((definition) => ({ ...definition, objects: [] }));
  return {
    mode,
    sections,
    desktopColumns: { left: "plan", right: "evidence" },
    mobileOrder: sections.map((section) => section.id),
    claims: [],
    limitations: [],
    proposal: null,
    approval: null,
    canDecideApproval: false,
    replayMessage: null,
  };
}

function parseArtifact(artifact: RedactedArtifact, sequence: number): PlanEvidenceObjectView {
  const envelope = objectRecord(artifact.payload);
  const data = envelope && "data" in envelope ? (envelope.data as JsonValue) : artifact.payload;
  return {
    ref: envelope ? text(envelope.ref) || `legacy-${sequence}-${artifact.kind}` : `legacy-${sequence}-${artifact.kind}`,
    kind: artifact.kind,
    label: artifact.label,
    data,
    evidenceRefs: envelope ? stringArray(envelope.evidenceRefs) : [],
  };
}

function parseClaims(data: JsonValue, byRef: Map<string, PlanEvidenceObjectView>): PlanEvidenceClaimView[] {
  const record = objectRecord(data);
  if (!record || !Array.isArray(record.claims)) return [];
  return record.claims.flatMap((entry) => {
    const claim = objectRecord(entry);
    if (!claim) return [];
    const evidenceRefs = stringArray(claim.evidenceRefs);
    const evidenceTargets = evidenceRefs.flatMap((ref) => {
      const target = byRef.get(ref);
      return target ? [target] : [];
    });
    return [{
      claimId: text(claim.claimId),
      text: text(claim.text),
      evidenceRefs,
      evidenceTargets,
      supported: evidenceRefs.length > 0 && evidenceTargets.length === evidenceRefs.length,
    }];
  });
}

function isPartialObject(object: PlanEvidenceObjectView): boolean {
  const data = objectRecord(object.data);
  if (!data) return false;
  const state = text(data.state);
  const completeness = text(data.completeness);
  return ["FAILED", "TIMED_OUT", "CANCELLED", "BLOCKED_DEPENDENCY", "BLOCKED_APPROVAL"].includes(state)
    || completeness === "partial"
    || completeness === "incomplete";
}

function readLimitationDetails(value: JsonValue): string[] {
  const record = objectRecord(value);
  if (!record || !Array.isArray(record.limitations)) return [];
  return record.limitations.flatMap((entry) => {
    if (typeof entry === "string") return [entry];
    const limitation = objectRecord(entry);
    return limitation && typeof limitation.detail === "string" ? [limitation.detail] : [];
  });
}

function objectRecord(value: unknown): Record<string, JsonValue> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, JsonValue>
    : null;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}
