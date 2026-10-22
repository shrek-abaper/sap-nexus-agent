import type { DshCapabilityCatalogResult, DshMasterDataDirectoryResult } from "./types";

/**
 * Pure section models + type guards for the discovery tool cards
 * (list_master_data / list_capabilities). Kept separate from
 * ToolCallCard.tsx so they are testable without a DOM.
 */

export function isMasterDataDirectoryResult(
  result: unknown,
): result is DshMasterDataDirectoryResult {
  return (
    typeof result === "object" &&
    result !== null &&
    (result as { kind?: unknown }).kind === "master-data-directory"
  );
}

export function isCapabilityCatalogResult(
  result: unknown,
): result is DshCapabilityCatalogResult {
  return (
    typeof result === "object" &&
    result !== null &&
    (result as { kind?: unknown }).kind === "capability-catalog"
  );
}

export function isDiscoveryResult(result: unknown): boolean {
  return isMasterDataDirectoryResult(result) || isCapabilityCatalogResult(result);
}

export interface DirectorySections {
  meta: string;
  entries: string[];
  truncated: boolean;
}

export function directorySections(result: DshMasterDataDirectoryResult): DirectorySections {
  return {
    meta: `对象类型 ${result.objectType} · 快照 ${result.snapshotId ?? "unknown"} · 提取时间 ${result.sourceExtractedAt ?? "unknown"}`,
    entries: (result.candidates ?? []).map((candidate, index) => {
      const details = [
        ...Object.entries(candidate.distinguishing ?? {})
          .filter(([, value]) => value)
          .map(([key, value]) => `${key}=${value}`),
        ...(candidate.orgScopes ?? []).map((scope) => `${scope.field}=${scope.value}`),
      ].join("，");
      return `${index + 1}. ${candidate.displayName || "（无描述）"}（${candidate.canonicalCode}）${details ? ` — ${details}` : ""}`;
    }),
    truncated: result.resultCompleteness === "partial-truncated",
  };
}

export interface CatalogSections {
  meta: string;
  entries: { capabilityId: string; label: string; description: string }[];
}

export function catalogSections(result: DshCapabilityCatalogResult): CatalogSections {
  return {
    meta: `注册中心快照 ${result.snapshotId ?? "unknown"} · 共 ${(result.capabilities ?? []).length} 项`,
    entries: (result.capabilities ?? []).map((entry) => {
      const kind = entry.sideEffect === "none"
        ? "只读"
        : entry.requiresApproval ? "写入·需人工审批" : "写入";
      const required = entry.requiredInputs.length > 0
        ? `（必需参数：${entry.requiredInputs.join("、")}）`
        : "";
      return {
        capabilityId: entry.capabilityId,
        label: `${entry.domain} · ${kind}${required}`,
        description: entry.description,
      };
    }),
  };
}
