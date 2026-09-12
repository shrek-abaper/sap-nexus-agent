import type { Context } from "@deepseek-ai/cordis";
import { defineTool } from "@deepseek-ai/dsh-tools";
import type { PreToolDecision } from "@deepseek-ai/dsh-tools";
import {
  callDiagnoseMaterialSupply,
  SEMANTIC_TOOL_NAME,
  type SemanticToolResponse,
} from "./facade-client.js";

export const FACADE_URL_ENV = "SAP_NEXUS_FACADE_URL";
export const FACADE_TIMEOUT_ENV = "SAP_NEXUS_FACADE_TIMEOUT_MS";
const DEFAULT_FACADE_URL = "http://127.0.0.1:3000";

export type SapNexusToolConfig = {
  facadeUrl?: string;
  timeoutMs?: number;
};

// Deterministic, data-free presentation code only: it never inspects governed
// parameters beyond what the server returned, and contains no resolution,
// capability selection, or authorization logic.
export function renderDiagnosis(value: SemanticToolResponse): string {
  const lines: string[] = [];
  if (value.narrative.summary) lines.push(value.narrative.summary);
  if (value.status !== "complete") {
    lines.push(`[status=${value.status}]`);
  }
  for (const limitation of value.limitations) lines.push(`- ${limitation}`);
  if (value.error) lines.push(`error: ${value.error.errorType}: ${value.error.message}`);
  lines.push(`runId=${value.runId} chain=${value.capabilityChain.map((entry) => entry.capabilityId).join(">") || "(none)"}`);
  return lines.join("\n");
}

export const name = "sap-nexus-tools";
export const inject = ["tools"] as const;

export function apply(ctx: Context, config: SapNexusToolConfig = {}): void {
  const facadeUrl = config.facadeUrl
    ?? process.env[FACADE_URL_ENV]
    ?? DEFAULT_FACADE_URL;
  const timeoutMs = config.timeoutMs
    ?? Number(process.env[FACADE_TIMEOUT_ENV] ?? "60000");

  // tools waterfall, pre-execute stage: LOCAL shape validation only.
  // The server contract stays the authoritative validator.
  ctx.on(
    "tools/pre-execute",
    (exec, next): Promise<PreToolDecision> => {
      if (exec.name !== SEMANTIC_TOOL_NAME) return next();
      const args = exec.arguments;
      if (typeof args !== "object" || args === null) {
        return Promise.resolve({ kind: "deny", reason: "arguments must be an object" });
      }
      const utterance = (args as Record<string, unknown>).utterance;
      if (typeof utterance !== "string" || utterance.trim().length === 0) {
        return Promise.resolve({ kind: "deny", reason: "utterance must be a non-empty string" });
      }
      return next();
    },
  );

  ctx.tools.register(defineTool({
    name: SEMANTIC_TOOL_NAME,
    description: [
      "诊断 SAP 物料供应：回答某物料在某工厂「够不够用、在途多少」一类只读业务问题。",
      "输入自然语言问题，可选物料号与工厂；服务端完成语义解析、计划与执行，",
      "返回带证据血缘的库存/在途事实与结论。不接受任何 RFC、端点、绑定或凭证参数。",
    ].join(""),
    parameters: {
      utterance: {
        type: "string",
        required: true,
        description: "完整的自然语言业务问题，例如：A100 在 1000 工厂够不够用、在途多少？",
      },
      material: { type: "string", description: "可选物料编号（如 A100）" },
      plant: { type: "string", description: "可选工厂编码（如 1000）" },
      module: { type: "string", enum: ["MM", "SD", "FI"], description: "可选模块提示" },
      periodHint: { type: "string", description: "可选时间范围提示" },
    },
    output: {
      schema: { type: "json" },
      render: (_args, value) => [{ type: "text", text: renderDiagnosis(value as SemanticToolResponse) }],
    },
    async execute(args, exec): Promise<SemanticToolResponse> {
      const started = Date.now();
      try {
        const result = await callDiagnoseMaterialSupply({
          baseUrl: facadeUrl,
          utterance: args.utterance,
          material: args.material,
          plant: args.plant,
          module: args.module as "MM" | "SD" | "FI" | undefined,
          periodHint: args.periodHint,
          timeoutMs,
          signal: exec.signal,
        });
        // Local telemetry only (no governed payload values).
        process.stderr.write(JSON.stringify({
          ts: new Date().toISOString(),
          event: "semantic_tool.completed",
          tool: SEMANTIC_TOOL_NAME,
          status: result.status,
          runId: result.runId,
          chainLength: result.capabilityChain.length,
          durationMs: Date.now() - started,
        }) + "\n");
        return result;
      } catch (error) {
        process.stderr.write(JSON.stringify({
          ts: new Date().toISOString(),
          event: "semantic_tool.failed",
          tool: SEMANTIC_TOOL_NAME,
          error: error instanceof Error ? error.message : String(error),
          durationMs: Date.now() - started,
        }) + "\n");
        throw error;
      }
    },
  }));

  ctx.logger?.info(`[sap-nexus-tools] ${SEMANTIC_TOOL_NAME} -> ${facadeUrl}`);
}
