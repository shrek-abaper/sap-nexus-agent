import {
  DIAGNOSE_MATERIAL_SUPPLY,
  PROPOSE_REPLENISHMENT,
  REVIEW_CUSTOMER_EXPOSURE,
  REVIEW_VENDOR_EXPOSURE,
  SEMANTIC_TOOL_CONTRACT_VERSION,
  SEMANTIC_TOOL_NAMES,
  type SemanticToolName,
  type SemanticToolRequest,
} from "./types";
import { SemanticToolRequestError } from "./types";

// Mirror of the server-side forbidden technical-key policy (event projector's
// FORBIDDEN_TECHNICAL_KEY plus credential/endpoint terms). Checked at any depth.
const TECHNICAL_OVERRIDE_KEYS = new Set([
  "rfcname",
  "bindingid",
  "executorbindingid",
  "technicalbinding",
  "url",
  "endpoint",
  "httpmethod",
  "credentialref",
  "token",
  "apikey",
  "sql",
  "rawgatewaypayload",
  "method",
  "http",
  "credential",
]);

const ALLOWED_TOP_LEVEL = new Set([
  "contractVersion",
  "tool",
  "utterance",
  "slots",
  "context",
  "conversationId",
]);

const ALLOWED_SLOT_KEYS = new Set([
  "material",
  "plant",
  "customerNumber",
  "vendor",
  "companyCode",
  "requiredQuantity",
  "targetDate",
  "purchasingGroup",
]);

const ALLOWED_CONTEXT_KEYS = new Set(["plantScope", "module", "periodHint"]);

const V1_TOOLS: ReadonlySet<string> = new Set([DIAGNOSE_MATERIAL_SUPPLY]);
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function scanForTechnicalKeys(record: Record<string, unknown>, path = ""): string | null {
  for (const [key, value] of Object.entries(record)) {
    const normalized = key.toLowerCase();
    if (TECHNICAL_OVERRIDE_KEYS.has(normalized)) {
      return path ? `${path}.${key}` : key;
    }
    if (isRecord(value)) {
      const nested = scanForTechnicalKeys(value, path ? `${path}.${key}` : key);
      if (nested) return nested;
    }
  }
  return null;
}

const REQUIRED_SLOTS: Record<SemanticToolName, string[]> = {
  [DIAGNOSE_MATERIAL_SUPPLY]: [],
  [REVIEW_CUSTOMER_EXPOSURE]: ["customerNumber"],
  [REVIEW_VENDOR_EXPOSURE]: ["vendor", "companyCode"],
  [PROPOSE_REPLENISHMENT]: ["material", "plant", "requiredQuantity", "targetDate", "purchasingGroup"],
};

export function validateSemanticToolRequest(raw: unknown): SemanticToolRequest {
  if (!isRecord(raw)) {
    throw new SemanticToolRequestError("INVALID_REQUEST", "Request body must be a JSON object", 400);
  }

  const technicalPath = scanForTechnicalKeys(raw);
  if (technicalPath) {
    throw new SemanticToolRequestError(
      "TECHNICAL_OVERRIDE_REJECTED",
      `Technical binding fields are not accepted by the semantic tool facade (field: ${technicalPath})`,
      400,
    );
  }

  for (const key of Object.keys(raw)) {
    if (!ALLOWED_TOP_LEVEL.has(key)) {
      throw new SemanticToolRequestError(
        "INVALID_REQUEST",
        `Unknown request field: ${key}`,
        400,
      );
    }
  }

  const version = raw.contractVersion;
  if (version !== 1 && version !== SEMANTIC_TOOL_CONTRACT_VERSION) {
    throw new SemanticToolRequestError(
      "INVALID_REQUEST",
      `Unsupported contractVersion: ${String(version)}`,
      400,
    );
  }

  const tool = raw.tool;
  if (typeof tool !== "string" || !(SEMANTIC_TOOL_NAMES as readonly string[]).includes(tool)) {
    throw new SemanticToolRequestError(
      "UNKNOWN_SEMANTIC_TOOL",
      `Unknown semantic tool: ${String(tool)}`,
      404,
    );
  }
  if (version === 1 && !V1_TOOLS.has(tool)) {
    throw new SemanticToolRequestError(
      "UNKNOWN_SEMANTIC_TOOL",
      `Tool ${tool} requires contractVersion ${SEMANTIC_TOOL_CONTRACT_VERSION}`,
      404,
    );
  }

  if (typeof raw.utterance !== "string" || raw.utterance.trim().length === 0) {
    throw new SemanticToolRequestError("INVALID_REQUEST", "utterance must be a non-empty string", 400);
  }

  const slots = isRecord(raw.slots) ? raw.slots : {};
  for (const key of Object.keys(slots)) {
    if (!ALLOWED_SLOT_KEYS.has(key)) {
      throw new SemanticToolRequestError("INVALID_REQUEST", `Unknown slot: ${key}`, 400);
    }
  }
  const context = isRecord(raw.context) ? raw.context : {};
  for (const key of Object.keys(context)) {
    if (!ALLOWED_CONTEXT_KEYS.has(key)) {
      throw new SemanticToolRequestError("INVALID_REQUEST", `Unknown context field: ${key}`, 400);
    }
  }
  if (context.module !== undefined && context.module !== "MM" && context.module !== "SD" && context.module !== "FI") {
    throw new SemanticToolRequestError("INVALID_REQUEST", "context.module must be one of MM, SD, FI", 400);
  }

  for (const required of REQUIRED_SLOTS[tool as SemanticToolName]) {
    const value = slots[required];
    const missing = value === undefined || value === null || (typeof value === "string" && value.trim() === "");
    if (missing) {
      throw new SemanticToolRequestError(
        "MISSING_REQUIRED_SLOT",
        `Tool ${tool} requires slot: ${required}`,
        400,
      );
    }
  }

  if (PROPOSE_REPLENISHMENT === tool) {
    if (typeof slots.requiredQuantity !== "number" || !(slots.requiredQuantity > 0)) {
      throw new SemanticToolRequestError("INVALID_REQUEST", "requiredQuantity must be a positive number", 400);
    }
    if (typeof slots.targetDate !== "string" || !DATE_RE.test(slots.targetDate)) {
      throw new SemanticToolRequestError("INVALID_REQUEST", "targetDate must be YYYY-MM-DD", 400);
    }
    const group = slots.purchasingGroup;
    if (typeof group !== "string" || !/^[A-Za-z0-9]{1,3}$/.test(group)) {
      throw new SemanticToolRequestError("INVALID_REQUEST", "purchasingGroup must be 1-3 alphanumeric chars", 400);
    }
  }

  if (raw.conversationId !== undefined && typeof raw.conversationId !== "string") {
    throw new SemanticToolRequestError("INVALID_REQUEST", "conversationId must be a string", 400);
  }

  return {
    contractVersion: version,
    tool: tool as SemanticToolName,
    utterance: raw.utterance.trim(),
    slots: slots as SemanticToolRequest["slots"],
    context: context as SemanticToolRequest["context"],
    conversationId: typeof raw.conversationId === "string" ? raw.conversationId : undefined,
  };
}

// Deterministic server-side query rendering. For the governed Python/TS chain
// the semantic slots are appended as known-condition hints; resolution stays
// server-owned. (R-1/R-2 transition: harness never supplies execution bindings.)
export function buildToolQuery(request: SemanticToolRequest): string {
  const hints: string[] = [];
  const slots = request.slots ?? {};
  const add = (label: string, value: unknown) => {
    if (value !== undefined && value !== null && String(value) !== "") hints.push(`${label}: ${String(value)}`);
  };
  add("物料", slots.material);
  add("工厂", slots.plant ?? request.context?.plantScope);
  add("客户", slots.customerNumber);
  add("供应商", slots.vendor);
  add("公司代码", slots.companyCode);
  add("需求量", slots.requiredQuantity);
  add("目标交货日期", slots.targetDate);
  add("采购组", slots.purchasingGroup);
  add("模块", request.context?.module);
  add("时间", request.context?.periodHint);
  return hints.length === 0
    ? request.utterance
    : `${request.utterance}\n[已知条件] ${hints.join("；")}`;
}
