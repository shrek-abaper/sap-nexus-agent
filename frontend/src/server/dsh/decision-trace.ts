import "server-only";

import { appendFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { sha256Hex } from "../../runtime/durable/canonical-json";

// TypeScript counterpart of the Python decision-trace recorder
// (agent/sap_nexus_agent/decision_traces.py): one redacted JSONL line per
// chat turn. The chat path runs the in-process dsh runtime, so the Python
// run_query wrapper never sees these turns.

const DISABLED_VALUES = new Set(["", "0", "off", "false", "no"]);
const FORBIDDEN_KEYS = new Set([
  "credential", "credentials", "password", "token", "apikey", "key",
  "secret", "url", "sql", "rawresponse", "rawsappayload",
]);

type ToolCall = {
  name?: string;
  status?: string;
  args?: unknown;
  result?: {
    status?: string;
    capabilityChain?: { capabilityId?: string; state?: string }[];
    error?: { errorType?: string };
  };
};

export type TraceTurnInput = {
  conversationId: string;
  userText: string;
  toolCalls?: ToolCall[];
  errorMessage?: string;
};

function tracePath(): string | null {
  const configured = process.env.SAP_NEXUS_DECISION_TRACE;
  const raw = configured
    ?? path.resolve(process.cwd(), "../runtime/traces/decisions.jsonl");
  if (DISABLED_VALUES.has(raw.trim().toLowerCase())) return null;
  return path.resolve(raw);
}

// SemanticToolStatus -> five-state decision (see semantic-tools/types).
function mapDecision(status: string | undefined): string {
  switch (status) {
    case "complete":
    case "partial":
    case "awaiting_approval":
      return "SELECT";
    case "clarification":
      return "CLARIFY";
    default:
      return "REJECT";
  }
}

function filterParameters(args: unknown): Record<string, string> {
  if (!args || typeof args !== "object") return {};
  const filtered: Record<string, string> = {};
  for (const [key, value] of Object.entries(args)) {
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) continue;
    filtered[key] = String(value);
  }
  return filtered;
}

export function buildTraceRecord(input: TraceTurnInput): Record<string, unknown> {
  const primary = input.toolCalls?.find((call) => call.result) ?? input.toolCalls?.[0];
  const result = primary?.result;
  const toolStatus = result?.status ?? (input.errorMessage ? "error" : undefined);
  const semanticResult = result && "capabilityChain" in result ? result : undefined;
  const capabilityEntry = semanticResult?.capabilityChain?.find((entry) => entry.state === "executed");

  return {
    schema: "sap-nexus.decision-trace.v1",
    traceId: `dtrace-${randomUUID()}`,
    recordedAt: new Date().toISOString(),
    utteranceHash: sha256Hex(input.userText),
    decision: input.errorMessage ? null : mapDecision(toolStatus),
    capabilityId: capabilityEntry?.capabilityId ?? null,
    tool: primary?.name ?? null,
    toolStatus: toolStatus ?? null,
    parameters: filterParameters(primary?.args),
    errorType: result?.error?.errorType ?? null,
    conversationId: input.conversationId,
    model: "dsh",
  };
}

/** Append one turn; best effort, never throws into the request path. */
export function recordDshTurn(input: TraceTurnInput): void {
  const target = tracePath();
  if (target === null) return;
  try {
    mkdirSync(path.dirname(target), { recursive: true });
    const record = buildTraceRecord(input);
    appendFileSync(target, `${JSON.stringify(record)}\n`, "utf8");
  } catch {
    // Tracing must not break chat; mirror the Python recorder.
  }
}
