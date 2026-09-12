import type { AgentRunEvent } from "../run-event-schema";
import {
  DIAGNOSE_MATERIAL_SUPPLY,
  PROPOSE_REPLENISHMENT,
  SEMANTIC_TOOL_CONTRACT_VERSION,
  type ApprovalHandle,
  type CapabilityChainEntry,
  type ResolvedSemanticValue,
  type SemanticToolFact,
  type SemanticToolName,
  type SemanticToolResponse,
} from "./types";

type ArtifactData = Record<string, unknown>;

function artifactData(event: AgentRunEvent): ArtifactData | null {
  const payload = event.artifact?.payload;
  if (typeof payload !== "object" || payload === null) return null;
  const record = payload as Record<string, unknown>;
  // Composition evidence events wrap the object payload under `data`;
  // legacy workbench events carry the object directly.
  if (typeof record.data === "object" && record.data !== null) {
    return record.data as ArtifactData;
  }
  return record;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function isTerminal(event: AgentRunEvent): boolean {
  return event.type === "run_completed"
    || event.type === "run_failed"
    || event.state === "awaiting_approval"
    || event.state === "awaiting_batch_confirm"
    || event.state === "rejected";
}

export function terminalEvent(events: AgentRunEvent[]): AgentRunEvent | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (isTerminal(events[index])) return events[index];
  }
  return null;
}

function uniqueValues(values: ResolvedSemanticValue[]): ResolvedSemanticValue[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const key = `${value.type}|${value.value}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function limitationText(limitation: unknown): string | null {
  if (typeof limitation === "string") return limitation;
  if (limitation && typeof limitation === "object") {
    const record = limitation as Record<string, unknown>;
    const kind = asString(record.kind);
    const detail = asString(record.detail);
    if (kind && detail) return `${kind}: ${detail}`;
    return kind ?? detail;
  }
  return null;
}

export function mapDiagnoseEvents(
  events: AgentRunEvent[],
  runId: string,
  tool: SemanticToolName = DIAGNOSE_MATERIAL_SUPPLY,
): SemanticToolResponse {
  const terminal = terminalEvent(events);

  const actionProposed = events.some((event) => event.type === "action_proposed")
    || terminal?.state === "awaiting_approval"
    || terminal?.state === "awaiting_batch_confirm";

  const nodeEvents = events.filter((event) => event.type === "plan_node_state");
  const factEvents = events.filter((event) =>
    event.type === "fact_emitted" || event.type === "reasoning_fact_created");
  const projectionEvent = events.find((event) => event.type === "projection_completed");
  const narrativeEvent = events.find((event) => event.type === "narrative_completed")
    ?? events.find((event) => event.type === "narrative_created");

  const chain: CapabilityChainEntry[] = [];
  for (const event of nodeEvents) {
    const data = artifactData(event);
    const capabilityId = asString(data?.capabilityId);
    if (!capabilityId) continue;
    const ref = event.objectRefs?.[0]?.ref;
    const payload = event.artifact?.payload;
    const payloadEvidenceRefs = payload !== null && typeof payload === "object"
      ? (payload as Record<string, unknown>).evidenceRefs
      : undefined;
    const evidenceRefs = Array.isArray(payloadEvidenceRefs)
      ? payloadEvidenceRefs.filter((entry): entry is string => typeof entry === "string")
      : undefined;
    chain.push({
      capabilityId,
      state: asString(data?.state) ?? event.state,
      factRefs: ref ? Array.from(new Set([ref, ...(evidenceRefs ?? [])])) : evidenceRefs,
    });
  }

  // Legacy single-SELECT runs have no plan nodes: the executed capability is
  // carried on the gateway execution events.
  if (chain.length === 0) {
    for (const event of events) {
      if (event.type === "gateway_execute_completed" && event.capabilityId) {
        chain.push({ capabilityId: event.capabilityId, state: "executed" });
      }
    }
  }

  const facts: SemanticToolFact[] = [];
  for (const event of factEvents) {
    const data = artifactData(event);
    if (!data) continue;
    const asOf = asString(data.asOf);
    const factId = asString(data.factId) ?? undefined;
    const ref = event.objectRefs?.[0]?.ref ?? (factId ? `fact:${factId}` : undefined);
    if (!ref) continue;
    facts.push({
      ref,
      factId,
      material: typeof data.material === "string" ? data.material : null,
      plant: typeof data.plant === "string" ? data.plant : null,
      value: asNumberOrNull(data.value),
      unit: typeof data.unit === "string" ? data.unit : null,
      asOf: asOf ?? "",
      evidence: Array.isArray(data.evidence)
        ? data.evidence.filter((entry): entry is Record<string, unknown> =>
          typeof entry === "object" && entry !== null)
        : undefined,
    } as SemanticToolFact);
  }

  // SD/FI LIST facts carry customer/vendor identifiers in evidence rows.
  const evidenceParty = (fact: SemanticToolFact): { customer?: string; vendor?: string } => {
    const row = fact.evidence?.[0] as Record<string, unknown> | undefined;
    return {
      customer: asString(row?.soldTo) ?? asString(row?.customer) ?? undefined,
      vendor: asString(row?.supplier) ?? asString(row?.vendor) ?? undefined,
    };
  };

  const projectionData = projectionEvent ? artifactData(projectionEvent) : null;
  const projection = projectionData ? {
    ref: projectionEvent?.objectRefs?.[0]?.ref
      ?? `projection:${asString(projectionData.outputHash) ?? ""}`,
    completeness: (asString(projectionData.completeness) === "partial"
      || asString(projectionData.completeness) === "incomplete"
      ? asString(projectionData.completeness)
      : "complete") as "complete" | "partial" | "incomplete",
    asOf: asString(projectionData.asOf) ?? "",
    outputHash: asString(projectionData.outputHash) ?? undefined,
    limitations: Array.isArray(projectionData.limitations)
      ? projectionData.limitations.filter((entry): entry is Record<string, unknown> =>
        typeof entry === "object" && entry !== null)
      : [],
  } : undefined;

  const narrativeData = narrativeEvent ? artifactData(narrativeEvent) : null;
  const narrativeSummary = asString(narrativeData?.summary) ?? asString(narrativeData?.text) ?? "";
  const narrativeLimitations = Array.isArray(narrativeData?.limitations)
    ? narrativeData.limitations.map((entry) => (typeof entry === "string" ? entry : null))
        .filter((entry): entry is string => entry !== null)
    : [];

  const limitations: string[] = [];
  if (projection) {
    for (const entry of projection.limitations) {
      const text = limitationText(entry);
      if (text) limitations.push(text);
    }
  }
  for (const limitation of narrativeLimitations) limitations.push(limitation);

  const semanticValues: ResolvedSemanticValue[] = [];
  for (const fact of facts) {
    if (fact.material) {
      semanticValues.push({ type: "Material", value: fact.material, provenance: fact.ref });
    }
    if (fact.plant) {
      semanticValues.push({ type: "Plant", value: fact.plant, provenance: fact.ref });
    }
    const party = evidenceParty(fact);
    if (party.customer) {
      semanticValues.push({ type: "Customer", value: party.customer, provenance: fact.ref });
    }
    if (party.vendor) {
      semanticValues.push({ type: "Vendor", value: party.vendor, provenance: fact.ref });
    }
  }

  let status: SemanticToolResponse["status"];
  if (actionProposed) {
    status = tool === PROPOSE_REPLENISHMENT ? "awaiting_approval" : "out_of_scope";
  } else if (terminal?.type === "run_failed" || terminal?.state === "failed") {
    status = "failed";
  } else if (terminal?.state === "rejected") {
    status = "rejected";
  } else if (projection) {
    status = projection.completeness === "complete" ? "complete" : "partial";
    if (projection.completeness === "incomplete") status = "unavailable";
  } else if (facts.length > 0) {
    status = "complete";
  } else {
    // A settled READ run without facts means the intent could not be resolved
    // to an executable single-capability/composition answer.
    status = "clarification";
  }

  const response: SemanticToolResponse = {
    contractVersion: SEMANTIC_TOOL_CONTRACT_VERSION,
    tool,
    status,
    runId,
    resolved: { semanticValues: uniqueValues(semanticValues) },
    capabilityChain: chain,
    facts,
    narrative: {
      summary: narrativeSummary,
      limitations: narrativeLimitations,
      evidenceRefs: Array.isArray(narrativeData?.evidenceRefs)
        ? narrativeData.evidenceRefs.filter((entry): entry is string => typeof entry === "string")
        : undefined,
    },
    limitations: Array.from(new Set(limitations)),
  };

  if (terminal?.traceId) response.traceId = terminal.traceId;
  if (projection) response.projection = projection;
  if (status === "failed" || status === "unavailable") {
    response.error = terminal?.error
      ? { errorType: terminal.error.errorType, message: terminal.error.message }
      : { errorType: status === "failed" ? "SEMANTIC_TOOL_RUN_FAILED" : "SEMANTIC_TOOL_UNAVAILABLE",
          message: status === "failed" ? "The governed run failed" : "Upstream data is unavailable or incomplete" };
  }

  return response;
}
