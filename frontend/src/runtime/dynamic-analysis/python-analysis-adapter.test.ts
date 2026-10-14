import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AnalysisAdapterError,
  runPythonAnalysis,
  sanitizeChildEnvironment,
} from "./python-analysis-adapter";
import type { AnalysisWireInput } from "./types";

import { readFileSync } from "node:fs";
import path from "node:path";

function repoRoot(): string {
  return process.env.SAP_NEXUS_AGENT_ROOT
    ? path.dirname(process.env.SAP_NEXUS_AGENT_ROOT)
    : path.basename(process.cwd()) === "frontend"
      ? path.dirname(process.cwd())
      : process.cwd();
}

const root = repoRoot();
const releasePackage = JSON.parse(
  readFileSync(path.join(root, "ontology/generated/semantic-release.json"), "utf8"),
);
const release = {
  semanticSnapshotId: releasePackage.semanticSnapshotId,
  registrySnapshotId: releasePackage.registrySnapshotId,
};

function wireInput(): AnalysisWireInput {
  return {
    wireVersion: 1,
    runId: "run-test",
    release,
    nodeResults: [
      {
        nodeId: "read-1",
        capabilityId: "MM.PurchaseOrder.GetList",
        parameters: { material: "DEMOA2", "plant": "1000" },
        gatewayTraceId: "fake-1",
        executedAt: "2026-10-14T00:00:00Z",
        data: {
          purchaseOrders: [
            {
              purchaseOrder: "4500000001",
              purchaseOrderItem: "00010",
              supplier: "V72719",
              orderQuantity: "100",
              purchaseOrderUnit: "EA",
            },
            {
              purchaseOrder: "4500000001",
              purchaseOrderItem: "00020",
              supplier: "V72719",
              orderQuantity: "150",
              purchaseOrderUnit: "EA",
            },
          ],
        },
      },
    ],
    analysisPlan: {
      nodes: [
        {
          nodeId: "a1",
          operatorId: "group_sum",
          inputs: [
            {
              kind: "factField",
              factTypeId: "sapnexus:PurchaseOrderSupplyFact",
              field: "orderQuantity",
            },
          ],
          params: {
            dimensions: ["supplier"],
            measure: "orderQuantity",
            unitField: "purchaseOrderUnit",
          },
          dependsOn: [],
        },
      ],
      outputs: ["a1"],
    },
    requestedConclusions: [
      { id: "c1", statement: "grouped quantities", evidenceRequirement: "lineage" },
    ],
  };
}

describe("sanitizeChildEnvironment", () => {
  it("strips credentials and gateway/principal values", () => {
    const clean = sanitizeChildEnvironment(
      {
        NODE_ENV: "test",
        PATH: "/usr/bin",
        SAP_NEXUS_APPROVAL_TOKEN: "secret",
        SAP_NEXUS_GATEWAY_URL: "http://gateway",
        SAP_NEXUS_PRINCIPAL: "{}",
      } as NodeJS.ProcessEnv,
      "/repo/agent",
    );
    expect(clean.SAP_NEXUS_APPROVAL_TOKEN).toBeUndefined();
    expect(clean.SAP_NEXUS_GATEWAY_URL).toBeUndefined();
    expect(clean.SAP_NEXUS_PRINCIPAL).toBeUndefined();
    expect(clean.PATH).toBe("/usr/bin");
    expect(clean.PYTHONPATH).toContain("/repo/agent");
  });
});

describe.skipIf(!process.env.RUN_PYTHON_INTEGRATION)("runPythonAnalysis real child", () => {
  it("groups quantities over the wire", async () => {
    const output = await runPythonAnalysis(wireInput(), { timeoutMs: 30_000 });
    expect(output.status).toBe("complete");
    const result = output.results.find((r) => r.nodeId === "a1");
    expect(result?.rows[0]?.measures?.orderQuantity.decimal).toBe("250");
  });

  it("fails closed on unsupported wire version", async () => {
    const bad = { ...wireInput(), wireVersion: 99 as unknown as 1 };
    const output = await runPythonAnalysis(bad, { timeoutMs: 30_000 });
    expect(output.status).toBe("failed");
    expect(output.facts).toEqual([]);
    expect(output.results).toEqual([]);
  });

  it("aborts via signal", async () => {
    const controller = new AbortController();
    const promise = runPythonAnalysis(wireInput(), { signal: controller.signal });
    controller.abort();
    await expect(promise).rejects.toBeInstanceOf(AnalysisAdapterError);
  });
});
