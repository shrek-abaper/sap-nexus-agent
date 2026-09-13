import {
  PROPOSE_REPLENISHMENT,
  SemanticToolUpstreamError,
  type ApprovalHandle,
  type SemanticToolResponse,
} from "./types";
import { buildToolQuery, validateSemanticToolRequest } from "./validate";
import { mapDiagnoseEvents } from "./map-events";
import {
  createAgentRun,
  getAgentRunEvents,
  getAgentRunRecord,
} from "../agent-runtime-adapter";
import type { TrustedPrincipal } from "../principal/types";

const DEFAULT_TIMEOUT_MS = 120_000;

async function waitForTerminalEvents(
  runId: string,
  principal: TrustedPrincipal,
  timeoutMs: number,
  getEvents: typeof getAgentRunEvents,
): Promise<AgentRunEventLike[]> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const events = await getEvents(runId, principal);
    if (events.some((event) => isTerminal(event))) {
      return events;
    }
    if (Date.now() >= deadline) {
      throw new SemanticToolUpstreamError(
        "SEMANTIC_TOOL_TIMEOUT",
        `semantic tool run ${runId} did not settle within ${timeoutMs}ms`,
        504,
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
}

type AgentRunEventLike = Awaited<ReturnType<typeof getAgentRunEvents>>[number];

function isTerminal(event: AgentRunEventLike): boolean {
  return event.type === "run_completed" || event.type === "run_failed" ||
    event.state === "awaiting_approval" || event.state === "awaiting_batch_confirm" ||
    event.state === "rejected" || event.state === "failed";
}

function buildApprovalHandle(
  record: { pendingOutcome?: { approvalRecord?: unknown } | null },
  fallbackRunId: string,
): ApprovalHandle | undefined {
  const approval = record.pendingOutcome?.approvalRecord;
  if (!approval || typeof approval !== "object") return undefined;
  const r = approval as Record<string, unknown>;
  if (!r.approvalId || !r.expiresAt || !r.parameters) return undefined;
  return {
    approvalId: String(r.approvalId),
    // The python-built ApprovalRecord does not know the TS run id; the card
    // posts to /api/agent-runs/{runId}/approval, so an empty value would 404.
    runId: String(r.runId || fallbackRunId),
    expiresAt: String(r.expiresAt),
    capabilityId: String(r.capabilityId ?? ""),
    parameters: (r.parameters ?? {}) as Record<string, string>,
    parameterSources: r.parameterSources as ApprovalHandle["parameterSources"],
    factRefs: Array.isArray(r.factRefs) ? r.factRefs.map(String) : [],
    hashes: {
      subjectHash: String(r.subjectHash ?? ""),
      proposalHash: String(r.proposalHash ?? ""),
      parameterSnapshotHash: String(r.parameterSnapshotHash ?? ""),
    },
  };
}

export type ExecuteSemanticToolDeps = {
  createRun?: typeof createAgentRun;
  getEvents?: typeof getAgentRunEvents;
  getRecord?: typeof getAgentRunRecord;
  timeoutMs?: number;
};

// Server-side governed entry shared by the HTTP facade and the in-process dsh
// tool handlers. The harness names only a business tool + utterance/slots.
export async function executeSemanticTool(
  rawRequest: unknown,
  principal: TrustedPrincipal,
  deps: ExecuteSemanticToolDeps = {},
): Promise<SemanticToolResponse> {
  const request = validateSemanticToolRequest(rawRequest);
  const createRun = deps.createRun ?? createAgentRun;
  const getEvents = deps.getEvents ?? getAgentRunEvents;
  const getRecord = deps.getRecord ?? getAgentRunRecord;

  const { runId } = await createRun({
    query: buildToolQuery(request),
    conversationId: request.conversationId,
    principal,
  });
  const events = await waitForTerminalEvents(runId, principal, deps.timeoutMs ?? DEFAULT_TIMEOUT_MS, getEvents);
  const response = mapDiagnoseEvents(events, runId, request.tool);
  // Echo the request contract version: v1 diagnose callers keep a v1-shaped
  // response (diagnose only), while v2 callers receive the v2 surface.
  response.contractVersion = request.contractVersion;

  if (request.tool === PROPOSE_REPLENISHMENT && response.status === "awaiting_approval") {
    const record = await getRecord(runId, principal);
    const approval = record ? buildApprovalHandle(record, runId) : undefined;
    if (approval) response.approval = approval;
  }

  return response;
}
