import { describe, expect, it } from "vitest";

import {
  catalogSections,
  directorySections,
  isCapabilityCatalogResult,
  isMasterDataDirectoryResult,
} from "./directory-card";
import { isSemanticToolResult } from "./ontology-card";

const DIRECTORY_RESULT = {
  kind: "master-data-directory",
  status: "complete",
  objectType: "sapnexus:Material",
  candidates: [
    {
      canonicalCode: "DEMOA1",
      displayName: "蓝色耐高温密封圈 Ø20",
      matchKind: "browse",
      status: "active",
      distinguishing: { materialGroup: "SEAL" },
      orgScopes: [{ field: "plant", value: "1000" }],
    },
  ],
  snapshotId: "snap1",
  resultCompleteness: "partial-truncated",
  sourceExtractedAt: "2026-10-01",
  narrative: { summary: "…", limitations: [] },
} as const;

const CATALOG_RESULT = {
  kind: "capability-catalog",
  status: "complete",
  capabilities: [
    {
      capabilityId: "MM.PR.CreateDraft",
      name: "Create PR Draft",
      description: "创建采购申请草稿。",
      domain: "MM",
      sideEffect: "sap_write",
      requiresApproval: true,
      requiredInputs: ["material"],
    },
  ],
  snapshotId: "snap-reg",
} as const;

describe("discovery result guards", () => {
  it("discriminates the two discovery kinds", () => {
    expect(isMasterDataDirectoryResult(DIRECTORY_RESULT)).toBe(true);
    expect(isCapabilityCatalogResult(CATALOG_RESULT)).toBe(true);
    expect(isMasterDataDirectoryResult(CATALOG_RESULT)).toBe(false);
    expect(isCapabilityCatalogResult(DIRECTORY_RESULT)).toBe(false);
  });

  it("discovery results are not semantic tool results", () => {
    expect(isSemanticToolResult(DIRECTORY_RESULT)).toBe(false);
    expect(isSemanticToolResult(CATALOG_RESULT)).toBe(false);
    expect(isSemanticToolResult({ status: "complete", kind: undefined })).toBe(true);
  });
});

describe("directorySections", () => {
  it("renders meta, candidate lines, and truncation", () => {
    const sections = directorySections(DIRECTORY_RESULT as never);
    expect(sections.meta).toContain("sapnexus:Material");
    expect(sections.meta).toContain("snap1");
    expect(sections.entries).toEqual([
      "1. 蓝色耐高温密封圈 Ø20（DEMOA1） — materialGroup=SEAL，plant=1000",
    ]);
    expect(sections.truncated).toBe(true);
  });
});

describe("catalogSections", () => {
  it("renders entries with domain, write kind, and required inputs", () => {
    const sections = catalogSections(CATALOG_RESULT as never);
    expect(sections.meta).toContain("共 1 项");
    expect(sections.entries).toEqual([
      {
        capabilityId: "MM.PR.CreateDraft",
        label: "MM · 写入·需人工审批（必需参数：material）",
        description: "创建采购申请草稿。",
      },
    ]);
  });
});
