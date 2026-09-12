// The ONLY outbound business surface of this harness: the server-owned
// semantic tool facade. There is deliberately no Gateway client here — the
// harness can name neither capabilityId nor RFC/binding/endpoint.

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export const SEMANTIC_TOOL_NAME = "diagnose_material_supply" as const;
export const SEMANTIC_TOOL_CONTRACT_VERSION = 1 as const;
const DEFAULT_FACADE_PATH = "/api/semantic-tools";

export type SemanticToolStatus =
  | "complete"
  | "partial"
  | "clarification"
  | "out_of_scope"
  | "unavailable"
  | "rejected"
  | "failed";

export type SemanticToolResponse = {
  contractVersion: 1;
  tool: typeof SEMANTIC_TOOL_NAME;
  status: SemanticToolStatus;
  runId: string;
  traceId?: string;
  resolved: { semanticValues: Array<{ type: string; value: string; provenance: string }> };
  capabilityChain: Array<{ capabilityId: string; state: string; factRefs?: string[] }>;
  facts: Array<{
    ref: string;
    factId?: string;
    material: string | null;
    plant: string | null;
    value: number | null;
    unit: string | null;
    asOf: string;
  }>;
  projection?: {
    ref: string;
    completeness: "complete" | "partial" | "incomplete";
    asOf: string;
    outputHash?: string;
    limitations: JsonValue[];
  };
  narrative: { summary: string; limitations: string[]; evidenceRefs?: string[] };
  limitations: string[];
  error?: { errorType: string; message: string };
};

export type CallDiagnoseInput = {
  baseUrl: string;
  utterance: string;
  material?: string;
  plant?: string;
  module?: "MM" | "SD" | "FI";
  periodHint?: string;
  conversationId?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
};

export class FacadeContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FacadeContractError";
  }
}

export function facadeEndpoint(baseUrl: string): string {
  return baseUrl.endsWith("/")
    ? `${baseUrl}${DEFAULT_FACADE_PATH.slice(1)}`
    : `${baseUrl}${DEFAULT_FACADE_PATH}`;
}

// Local shape validation is a pre-execute convenience, never the sole
// validation: the server contract and the Gateway remain authoritative.
export function validateFacadeResponse(raw: unknown): SemanticToolResponse {
  if (typeof raw !== "object" || raw === null) {
    throw new FacadeContractError("facade response is not an object");
  }
  const record = raw as Record<string, unknown>;
  if (record.contractVersion !== SEMANTIC_TOOL_CONTRACT_VERSION) {
    throw new FacadeContractError(`unexpected contractVersion: ${String(record.contractVersion)}`);
  }
  if (record.tool !== SEMANTIC_TOOL_NAME) {
    throw new FacadeContractError(`unexpected tool: ${String(record.tool)}`);
  }
  if (typeof record.runId !== "string" || record.runId.length === 0) {
    throw new FacadeContractError("missing runId");
  }
  if (!Array.isArray(record.facts) || !Array.isArray(record.capabilityChain)) {
    throw new FacadeContractError("missing facts/capabilityChain arrays");
  }
  const narrative = record.narrative as { summary?: unknown } | undefined;
  if (!narrative || typeof narrative.summary !== "string") {
    throw new FacadeContractError("missing narrative.summary");
  }
  return record as unknown as SemanticToolResponse;
}

export async function callDiagnoseMaterialSupply(input: CallDiagnoseInput): Promise<SemanticToolResponse> {
  const controller = new AbortController();
  const timeout = AbortSignal.timeout(input.timeoutMs ?? 60_000);
  const abort = () => controller.abort();
  timeout.addEventListener("abort", abort, { once: true });
  input.signal?.addEventListener("abort", abort, { once: true });

  try {
    const response = await fetch(facadeEndpoint(input.baseUrl), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        contractVersion: SEMANTIC_TOOL_CONTRACT_VERSION,
        tool: SEMANTIC_TOOL_NAME,
        utterance: input.utterance,
        slots: {
          ...(input.material ? { material: input.material } : {}),
          ...(input.plant ? { plant: input.plant } : {}),
        },
        context: {
          ...(input.module ? { module: input.module } : {}),
          ...(input.periodHint ? { periodHint: input.periodHint } : {}),
        },
        ...(input.conversationId ? { conversationId: input.conversationId } : {}),
      }),
      signal: controller.signal,
    });

    const body = await response.json().catch(() => null) as unknown;
    if (!response.ok) {
      const errorType = typeof body === "object" && body !== null && "errorType" in body
        ? String((body as Record<string, unknown>).errorType)
        : "FACADE_HTTP_ERROR";
      const message = typeof body === "object" && body !== null && "message" in body
        ? String((body as Record<string, unknown>).message)
        : `facade HTTP ${response.status}`;
      throw new FacadeContractError(`${errorType}: ${message}`);
    }
    return validateFacadeResponse(body);
  } finally {
    timeout.removeEventListener("abort", abort);
    input.signal?.removeEventListener("abort", abort);
  }
}
