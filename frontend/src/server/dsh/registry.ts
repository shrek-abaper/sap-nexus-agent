import "server-only";
import {
  createDshRuntime,
  type DshRuntime,
  type ToolHandler,
} from "./runtime";
import { OpenAiCompatibleAdapter } from "./openai-compatible-adapter";
import { executeSemanticTool } from "../../runtime/semantic-tools/execute-tool";
import { PLACEHOLDER_PRINCIPAL } from "../../runtime/principal/types";
import {
  DIAGNOSE_MATERIAL_SUPPLY,
  PROPOSE_REPLENISHMENT,
  REVIEW_CUSTOMER_EXPOSURE,
  REVIEW_VENDOR_EXPOSURE,
  SEMANTIC_TOOL_NAMES,
  type SemanticToolResponse,
} from "../../runtime/semantic-tools/types";

// Server-only global singleton across Next dev HMR reloads (first dsh Context
// in this repo). The browser bundle never imports this module.
const globalForDsh = globalThis as unknown as {
  __sapNexusDshRuntime?: Promise<DshRuntime>;
};

const PROVIDER = "sapnexus";

function envModelConfig() {
  return {
    baseUrl: process.env.SAP_NEXUS_LLM_BASE_URL ?? process.env.LLM_BASE_URL ?? "https://api.deepseek.com",
    apiKey: process.env.SAP_NEXUS_LLM_API_KEY ?? process.env.LLM_API_KEY ?? "",
    model: process.env.SAP_NEXUS_LLM_MODEL ?? process.env.LLM_MODEL_NAME ?? "deepseek-chat",
  };
}

// Tool handlers run the SAME governed server entry as the HTTP facade; the
// in-process dsh tools never call HTTP or name capability/RFC/binding.
function buildHandlers(): Record<string, ToolHandler> {
  const handler = (tool: (typeof SEMANTIC_TOOL_NAMES)[number]): ToolHandler =>
    (args): Promise<SemanticToolResponse> => {
      const slots: Record<string, unknown> = {};
      for (const key of [
        "material", "plant", "customerNumber", "vendor", "companyCode",
        "requiredQuantity", "targetDate", "purchasingGroup",
      ]) {
        if (args[key] !== undefined) slots[key] = args[key];
      }
      return executeSemanticTool({
        contractVersion: 2,
        tool,
        utterance: typeof args.utterance === "string" ? args.utterance : "",
        slots,
      }, PLACEHOLDER_PRINCIPAL);
    };

  return {
    [DIAGNOSE_MATERIAL_SUPPLY]: handler(DIAGNOSE_MATERIAL_SUPPLY),
    [REVIEW_CUSTOMER_EXPOSURE]: handler(REVIEW_CUSTOMER_EXPOSURE),
    [REVIEW_VENDOR_EXPOSURE]: handler(REVIEW_VENDOR_EXPOSURE),
    [PROPOSE_REPLENISHMENT]: handler(PROPOSE_REPLENISHMENT),
  };
}

export async function getDshRuntime(): Promise<DshRuntime> {
  if (!globalForDsh.__sapNexusDshRuntime) {
    const config = envModelConfig();
    globalForDsh.__sapNexusDshRuntime = createDshRuntime({
      provider: PROVIDER,
      model: config.model,
      adapter: new OpenAiCompatibleAdapter(config),
      handlers: buildHandlers(),
    });
  }
  return globalForDsh.__sapNexusDshRuntime;
}

// Test/verification seam: install a scripted runtime (MockAdapter) without
// touching the production global.
export async function __setDshRuntimeForTests(runtime: DshRuntime | null): Promise<void> {
  if (runtime === null) {
    delete globalForDsh.__sapNexusDshRuntime;
  } else {
    globalForDsh.__sapNexusDshRuntime = Promise.resolve(runtime);
  }
}

export function dshModelConfigured(): boolean {
  return envModelConfig().apiKey.length > 0;
}
