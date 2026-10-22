import "server-only";
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

/**
 * Discovery tool handlers (list_master_data / list_capabilities).
 *
 * Both delegate to credential-free Python subprocesses over governed sources
 * (entity-resolution rules + registry snapshot); the frontend never names a
 * capabilityId itself — the object type is validated against the registered
 * ontology rules before anything runs. Responses carry deterministic Chinese
 * narratives with an explicit "no improvisation" guard line so the chat
 * model cannot pad the answer with invented codes.
 */

export const MASTER_DATA_DIRECTORY_TOOL = "list_master_data";
export const CAPABILITY_CATALOG_TOOL = "list_capabilities";

export type MasterDataDirectoryStatus =
  | "complete"
  | "unavailable"
  | "permission-denied"
  | "invalid"
  | "failed";

export interface MasterDataCandidate {
  canonicalCode: string;
  displayName: string;
  matchKind: string;
  status: string;
  distinguishing: Record<string, string>;
  orgScopes: { field: string; value: string }[];
}

export interface MasterDataDirectoryToolResponse {
  kind: "master-data-directory";
  contractVersion: 1;
  tool: typeof MASTER_DATA_DIRECTORY_TOOL;
  status: MasterDataDirectoryStatus;
  runId: string;
  objectType: string;
  candidates: MasterDataCandidate[];
  snapshotId?: string;
  resultCompleteness?: string;
  sourceExtractedAt?: string | null;
  narrative: { summary: string; limitations: string[] };
  limitations: string[];
  error?: { errorType: string; message: string };
}

export interface CapabilityCatalogEntry {
  capabilityId: string;
  name: string;
  description: string;
  domain: string;
  sideEffect: string;
  requiresApproval: boolean;
  requiredInputs: string[];
}

export interface CapabilityCatalogToolResponse {
  kind: "capability-catalog";
  contractVersion: 1;
  tool: typeof CAPABILITY_CATALOG_TOOL;
  status: "complete" | "failed";
  runId: string;
  capabilities: CapabilityCatalogEntry[];
  snapshotId?: string;
  narrative: { summary: string; limitations: string[] };
  limitations: string[];
  error?: { errorType: string; message: string };
}

export type DiscoveryRunner = (request: {
  mode: "master-data" | "capabilities";
  payload?: Record<string, unknown>;
}) => Promise<Record<string, unknown>>;

function repoRootPath(): string {
  if (process.env.SAP_NEXUS_AGENT_ROOT) return process.env.SAP_NEXUS_AGENT_ROOT;
  const cwd = process.cwd();
  return path.basename(cwd) === "frontend" ? path.dirname(cwd) : cwd;
}

function pythonExecutable(repoRoot: string): string {
  if (process.env.SAP_NEXUS_AGENT_PYTHON) return process.env.SAP_NEXUS_AGENT_PYTHON;
  const venv = path.join(repoRoot, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

function gatewayUrl(): string {
  return process.env.SAP_NEXUS_GATEWAY_URL
    || `http://127.0.0.1:${process.env.GATEWAY_PORT || "8080"}`;
}

const objectTypesCache = new Map<string, string[]>();

/** Registered master-data object types, parsed from the ontology rules file
 * (server-startup read; registering a new object type takes effect on
 * restart). Drives the tool's objectType enum so new types need no frontend
 * code change. */
export function masterDataObjectTypes(repoRoot: string = repoRootPath()): string[] {
  const cached = objectTypesCache.get(repoRoot);
  if (cached) return cached;
  const rulesPath = path.join(repoRoot, "ontology", "entity-resolution.yaml");
  let types: string[] = [];
  try {
    const text = readFileSync(rulesPath, "utf8");
    types = [...new Set(
      [...text.matchAll(/^\s*-\s+objectTypeId:\s*(\S+)\s*$/gm)].map((match) => match[1]),
    )];
  } catch {
    types = [];
  }
  objectTypesCache.set(repoRoot, types);
  return types;
}

/** Default runner: one credential-free Python subprocess per call. The
 * gateway URL goes only to the master-data mode as a CLI arg (the governed
 * MD search executes through it); the approval token never leaves. */
export function subprocessDiscoveryRunner(timeoutMs = 60_000): DiscoveryRunner {
  return (request) =>
    new Promise<Record<string, unknown>>((resolvePromise, rejectPromise) => {
      const repoRoot = repoRootPath();
      const env: Record<string, string | undefined> = {};
      for (const [key, value] of Object.entries(process.env)) {
        if (key === "SAP_NEXUS_APPROVAL_TOKEN") continue;
        if (key === "SAP_NEXUS_GATEWAY_URL") continue;
        if (key === "SAP_NEXUS_PRINCIPAL") continue;
        env[key] = value;
      }
      env.PYTHONPATH = [path.join(repoRoot, "agent"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter);

      const args = request.mode === "master-data"
        ? ["-m", "sap_nexus_agent.cli", "--list-master-data", "--gateway-url", gatewayUrl(), "--json"]
        : ["-m", "sap_nexus_agent.cli", "--list-capabilities", "--json"];

      let settled = false;
      let stdout = "";
      let stderr = "";
      const child = spawn(pythonExecutable(repoRoot), args, {
        cwd: repoRoot,
        env: env as NodeJS.ProcessEnv,
      });
      const timer = setTimeout(() => {
        child.kill();
        fail(new Error("discovery subprocess timed out"));
      }, timeoutMs);
      const fail = (error: Error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        rejectPromise(error);
      };
      child.stdout.on("data", (chunk: Buffer) => {
        stdout += chunk.toString("utf8");
      });
      child.stderr.on("data", (chunk: Buffer) => {
        stderr += chunk.toString("utf8");
      });
      child.on("error", (error) => fail(error));
      child.on("close", (code) => {
        if (settled) return;
        clearTimeout(timer);
        // Exit 0 = normal outcome; exit 1 = the CLI guard serialized an
        // unexpected failure as structured JSON. Both parse the same way.
        if (code === 0 || code === 1) {
          try {
            settled = true;
            resolvePromise(JSON.parse(stdout.trim()) as Record<string, unknown>);
          } catch {
            fail(new Error("discovery output is not valid JSON"));
          }
          return;
        }
        fail(new Error(`discovery exit ${code}: ${stderr.slice(-300)}`));
      });
      child.stdin.end(JSON.stringify(request.payload ?? {}));
    });
}

const OBJECT_TYPE_LABELS: Record<string, string> = {
  "sapnexus:Material": "物料",
  "sapnexus:Customer": "客户",
  "sapnexus:Supplier": "供应商",
};

export function objectTypeLabel(objectType: string): string {
  return OBJECT_TYPE_LABELS[objectType] ?? objectType;
}

function candidateLine(candidate: MasterDataCandidate, index: number): string {
  const details = [
    ...Object.entries(candidate.distinguishing)
      .filter(([, value]) => value)
      .map(([key, value]) => `${key}=${value}`),
    ...candidate.orgScopes.map((scope) => `${scope.field}=${scope.value}`),
  ].join("，");
  return `${index + 1}. ${candidate.displayName || "（无描述）"}（${candidate.canonicalCode}）${details ? ` — ${details}` : ""}`;
}

function directoryNarrative(
  status: MasterDataDirectoryStatus,
  objectType: string,
  candidates: MasterDataCandidate[],
  meta: { snapshotId?: string; sourceExtractedAt?: string | null; resultCompleteness?: string; message?: string },
): string {
  const label = objectTypeLabel(objectType);
  if (status !== "complete") {
    const reason = meta.message ?? "主数据检索失败。";
    return [
      `${label}主数据清单不可用：${reason}`,
      "",
      "未返回任何主数据；禁止列举或编造任何编号、名称或数据。",
    ].join("\n");
  }
  const lines: string[] = [
    `${label}主数据清单（快照 ${meta.snapshotId ?? "unknown"}，提取时间 ${meta.sourceExtractedAt ?? "unknown"}）：`,
    "",
    ...candidates.map(candidateLine),
  ];
  if (candidates.length === 0) {
    lines.push("（当前授权范围内没有匹配的主数据）");
  }
  if (meta.resultCompleteness === "partial-truncated") {
    lines.push("", "结果已按上限截断；可以补充检索词或组织范围缩小范围。");
  }
  lines.push("", "以上为系统返回的全部结果；禁止补充未列出的编号或名称。");
  return lines.join("\n");
}

function catalogNarrative(
  capabilities: CapabilityCatalogEntry[],
  snapshotId?: string,
): string {
  const lines: string[] = [
    `已注册能力目录（注册中心快照 ${snapshotId ?? "unknown"}，共 ${capabilities.length} 项）：`,
    "",
  ];
  for (const entry of capabilities) {
    const kind = entry.sideEffect === "none"
      ? "只读"
      : entry.requiresApproval ? "写入·需人工审批" : "写入";
    const required = entry.requiredInputs.length > 0
      ? `（必需参数：${entry.requiredInputs.join("、")}）`
      : "";
    lines.push(`- ${entry.capabilityId}（${entry.domain}，${kind}）：${entry.description}${required}`);
  }
  lines.push("", "以上为注册中心的全部能力；禁止声称存在未列出的能力。");
  return lines.join("\n");
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function toDirectoryResponse(
  objectType: string,
  payload: Record<string, unknown>,
): MasterDataDirectoryToolResponse {
  const status = (typeof payload.status === "string"
    ? payload.status
    : "failed") as MasterDataDirectoryStatus;
  const candidates: MasterDataCandidate[] = Array.isArray(payload.candidates)
    ? (payload.candidates as Record<string, unknown>[]).map((item) => ({
        canonicalCode: String(item.canonicalCode ?? ""),
        displayName: String(item.displayName ?? ""),
        matchKind: String(item.matchKind ?? ""),
        status: String(item.status ?? "active"),
        distinguishing: Object.fromEntries(
          Object.entries((item.distinguishing ?? {}) as Record<string, unknown>)
            .map(([key, value]) => [key, String(value)]),
        ),
        orgScopes: Array.isArray(item.orgScopes)
          ? (item.orgScopes as Record<string, unknown>[]).map((scope) => ({
              field: String(scope.field ?? ""),
              value: String(scope.value ?? ""),
            }))
          : [],
      }))
    : [];
  const meta = {
    snapshotId: typeof payload.snapshotId === "string" ? payload.snapshotId : undefined,
    resultCompleteness: typeof payload.resultCompleteness === "string" ? payload.resultCompleteness : undefined,
    sourceExtractedAt: typeof payload.sourceExtractedAt === "string" ? payload.sourceExtractedAt : null,
    message: typeof payload.message === "string" ? payload.message : undefined,
  };
  const response: MasterDataDirectoryToolResponse = {
    kind: "master-data-directory",
    contractVersion: 1,
    tool: MASTER_DATA_DIRECTORY_TOOL,
    status,
    runId: `dir-${objectType}`,
    objectType,
    candidates,
    snapshotId: meta.snapshotId,
    resultCompleteness: meta.resultCompleteness,
    sourceExtractedAt: meta.sourceExtractedAt,
    narrative: {
      summary: directoryNarrative(status, objectType, candidates, meta),
      limitations: [],
    },
    limitations: [],
  };
  if (status === "failed") {
    response.error = {
      errorType: "DIRECTORY_FAILED",
      message: meta.message ?? "unknown",
    };
  }
  return response;
}

function toCatalogResponse(
  payload: Record<string, unknown>,
): CapabilityCatalogToolResponse {
  const capabilities: CapabilityCatalogEntry[] = Array.isArray(payload.capabilities)
    ? (payload.capabilities as Record<string, unknown>[]).map((item) => ({
        capabilityId: String(item.capabilityId ?? ""),
        name: String(item.name ?? ""),
        description: String(item.description ?? ""),
        domain: String(item.domain ?? ""),
        sideEffect: String(item.sideEffect ?? "none"),
        requiresApproval: Boolean(item.requiresApproval),
        requiredInputs: asStringArray(item.requiredInputs),
      }))
    : [];
  const snapshotId = typeof payload.snapshotId === "string" ? payload.snapshotId : undefined;
  const complete = payload.status === "complete";
  const response: CapabilityCatalogToolResponse = {
    kind: "capability-catalog",
    contractVersion: 1,
    tool: CAPABILITY_CATALOG_TOOL,
    status: complete ? "complete" : "failed",
    runId: "catalog",
    capabilities,
    snapshotId,
    narrative: {
      summary: complete
        ? catalogNarrative(capabilities, snapshotId)
        : `能力目录不可用：${String(payload.message ?? "注册中心快照读取失败。")}`,
      limitations: [],
    },
    limitations: [],
  };
  if (!complete) {
    response.error = {
      errorType: "CATALOG_FAILED",
      message: String(payload.message ?? "unknown"),
    };
  }
  return response;
}

export function createMasterDataDirectoryHandler(
  runner: DiscoveryRunner = subprocessDiscoveryRunner(),
) {
  return async (args: Record<string, unknown>): Promise<MasterDataDirectoryToolResponse> => {
    const objectType = typeof args.objectType === "string" ? args.objectType : "";
    const registered = masterDataObjectTypes();
    if (registered.length > 0 && !registered.includes(objectType)) {
      return toDirectoryResponse(objectType, {
        status: "invalid",
        candidates: [],
        message: `未知的主数据对象类型 ${objectType || "（空）"}（已注册：${registered.join(", ")}）。`,
      });
    }
    const payload: Record<string, unknown> = { objectType };
    if (typeof args.query === "string" && args.query) payload.query = args.query;
    if (typeof args.orgFilter === "string" && args.orgFilter) payload.orgFilter = args.orgFilter;
    if (typeof args.limit === "number" && Number.isInteger(args.limit)) {
      payload.limit = Math.min(Math.max(args.limit, 1), 50);
    }
    const result = await runner({ mode: "master-data", payload });
    return toDirectoryResponse(objectType, result);
  };
}

export function createCapabilityCatalogHandler(
  runner: DiscoveryRunner = subprocessDiscoveryRunner(),
) {
  return async (_args: Record<string, unknown>): Promise<CapabilityCatalogToolResponse> => {
    const result = await runner({ mode: "capabilities" });
    return toCatalogResponse(result);
  };
}
