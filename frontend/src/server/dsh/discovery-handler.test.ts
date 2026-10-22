import { describe, expect, it } from "vitest";

import {
  CAPABILITY_CATALOG_TOOL,
  MASTER_DATA_DIRECTORY_TOOL,
  createCapabilityCatalogHandler,
  createMasterDataDirectoryHandler,
  masterDataObjectTypes,
  objectTypeLabel,
  type DiscoveryRunner,
} from "./discovery-handler";

const CANDIDATES = [
  {
    canonicalCode: "DEMOA1",
    displayName: "蓝色耐高温密封圈 Ø20",
    matchKind: "browse",
    status: "active",
    distinguishing: { materialGroup: "SEAL" },
    orgScopes: [{ field: "plant", value: "1000" }],
  },
  {
    canonicalCode: "DEMOA2",
    displayName: "蓝色耐高温密封圈 Ø25",
    matchKind: "browse",
    status: "active",
    distinguishing: {},
    orgScopes: [],
  },
];

function runnerReturning(payload: Record<string, unknown>): {
  runner: DiscoveryRunner;
  requests: { mode: string; payload?: Record<string, unknown> }[];
} {
  const requests: { mode: string; payload?: Record<string, unknown> }[] = [];
  return {
    requests,
    runner: async (request) => {
      requests.push(request);
      return payload;
    },
  };
}

describe("masterDataObjectTypes", () => {
  it("parses registered object types from the ontology rules file", () => {
    expect(masterDataObjectTypes()).toEqual(
      expect.arrayContaining(["sapnexus:Material", "sapnexus:Customer", "sapnexus:Supplier"]),
    );
  });

  it("falls back to an empty list for a missing rules file", () => {
    expect(masterDataObjectTypes("/nonexistent-repo-root")).toEqual([]);
  });
});

describe("list_master_data handler (injected runner)", () => {
  it("passes objectType/query/orgFilter through and renders a guarded narrative", async () => {
    const { runner, requests } = runnerReturning({
      status: "complete",
      candidates: CANDIDATES,
      snapshotId: "snap1",
      resultCompleteness: "partial-truncated",
      sourceExtractedAt: "2026-10-01",
    });
    const handler = createMasterDataDirectoryHandler(runner);

    const response = await handler({
      objectType: "sapnexus:Material",
      query: "密封圈",
      orgFilter: "1000",
      limit: 10,
    });

    expect(response.kind).toBe("master-data-directory");
    expect(response.tool).toBe(MASTER_DATA_DIRECTORY_TOOL);
    expect(response.status).toBe("complete");
    expect(requests[0]).toEqual({
      mode: "master-data",
      payload: { objectType: "sapnexus:Material", query: "密封圈", orgFilter: "1000", limit: 10 },
    });
    expect(response.candidates).toHaveLength(2);
    expect(response.narrative.summary).toContain("物料主数据清单（快照 snap1");
    expect(response.narrative.summary).toContain("1. 蓝色耐高温密封圈 Ø20（DEMOA1） — materialGroup=SEAL，plant=1000");
    expect(response.narrative.summary).toContain("结果已按上限截断");
    expect(response.narrative.summary).toContain("禁止补充未列出的编号");
  });

  it("omits empty optional params and clamps limit", async () => {
    const { runner, requests } = runnerReturning({ status: "complete", candidates: [] });
    const handler = createMasterDataDirectoryHandler(runner);

    await handler({ objectType: "sapnexus:Material", limit: 500 });

    expect(requests[0].payload).toEqual({ objectType: "sapnexus:Material", limit: 50 });
  });

  it("short-circuits unregistered object types without calling the runner", async () => {
    const { runner, requests } = runnerReturning({ status: "complete", candidates: [] });
    const handler = createMasterDataDirectoryHandler(runner);

    const response = await handler({ objectType: "sapnexus:Nope" });

    expect(response.status).toBe("invalid");
    expect(response.narrative.summary).toContain("sapnexus:Material");
    expect(response.narrative.summary).toContain("禁止列举或编造");
    expect(requests).toHaveLength(0);
  });

  it("maps provider-unavailable to a guarded unavailable narrative", async () => {
    const { runner } = runnerReturning({
      status: "unavailable",
      candidates: [],
      message: "主数据检索服务暂时不可用，请确认主数据服务已启动后重试。",
    });
    const handler = createMasterDataDirectoryHandler(runner);

    const response = await handler({ objectType: "sapnexus:Material" });

    expect(response.status).toBe("unavailable");
    expect(response.narrative.summary).toContain("暂时不可用");
    expect(response.narrative.summary).toContain("禁止列举或编造任何编号");
  });
});

describe("list_capabilities handler (injected runner)", () => {
  it("projects catalog entries into a guarded narrative", async () => {
    const { runner, requests } = runnerReturning({
      status: "complete",
      snapshotId: "snap-reg",
      capabilities: [
        {
          capabilityId: "MM.Inventory.GetAvailability",
          name: "Get Availability",
          description: "Read the MD04 stock/requirements list.",
          domain: "MM",
          sideEffect: "none",
          requiresApproval: false,
          requiredInputs: ["material", "plant"],
        },
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
    });
    const handler = createCapabilityCatalogHandler(runner);

    const response = await handler({});

    expect(response.kind).toBe("capability-catalog");
    expect(response.tool).toBe(CAPABILITY_CATALOG_TOOL);
    expect(response.status).toBe("complete");
    expect(requests[0]).toEqual({ mode: "capabilities" });
    expect(response.narrative.summary).toContain("共 2 项");
    expect(response.narrative.summary).toContain(
      "MM.Inventory.GetAvailability（MM，只读）：Read the MD04 stock/requirements list.（必需参数：material、plant）",
    );
    expect(response.narrative.summary).toContain("MM.PR.CreateDraft（MM，写入·需人工审批）");
    expect(response.narrative.summary).toContain("禁止声称存在未列出的能力");
  });

  it("surfaces catalog failure as structured error", async () => {
    const { runner } = runnerReturning({ status: "failure", message: "boom" });
    const handler = createCapabilityCatalogHandler(runner);

    const response = await handler({});

    expect(response.status).toBe("failed");
    expect(response.error).toEqual({ errorType: "CATALOG_FAILED", message: "boom" });
    expect(response.narrative.summary).toContain("能力目录不可用");
  });
});

describe("objectTypeLabel", () => {
  it("glosses known types and passes unknown ids through", () => {
    expect(objectTypeLabel("sapnexus:Material")).toBe("物料");
    expect(objectTypeLabel("sapnexus:CostCenter")).toBe("sapnexus:CostCenter");
  });
});
