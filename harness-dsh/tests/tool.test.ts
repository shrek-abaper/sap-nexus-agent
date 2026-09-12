import { afterEach, describe, expect, it } from "vitest";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { Context } from "@deepseek-ai/cordis";
import { mountSpine } from "../src/spine.js";
import { runTurn } from "../src/runner.js";
import { apply as registerSapNexusTool, name as pluginName } from "../src/sap-nexus-tool.js";
import { MockAdapter, textResponse, toolCallResponse } from "./mock-llm.js";
import type { SemanticToolResponse } from "../src/facade-client.js";

const PROVIDER = "sapnexus-mock";
const MODEL = "mock-model";

function cannedFacadeResponse(): SemanticToolResponse {
  return {
    contractVersion: 1,
    tool: "diagnose_material_supply",
    status: "complete",
    runId: "run-fixture-1",
    traceId: "trace-fixture-1",
    resolved: {
      semanticValues: [
        { type: "Material", value: "A100", provenance: "fact:inv-1" },
        { type: "Plant", value: "1000", provenance: "fact:inv-1" },
      ],
    },
    capabilityChain: [
      { capabilityId: "MM.Inventory.GetAvailability", state: "succeeded", factRefs: ["fact:inv-1"] },
      { capabilityId: "MM.PurchaseOrder.GetList", state: "succeeded", factRefs: ["fact:po-1"] },
    ],
    facts: [
      { ref: "fact:inv-1", factId: "inv-1", material: "A100", plant: "1000", value: 42, unit: "KG", asOf: "2026-09-11T08:00:00Z" },
      { ref: "fact:po-1", factId: "po-1", material: "A100", plant: "1000", value: 100, unit: "KG", asOf: "2026-09-11T08:00:00Z" },
    ],
    projection: {
      ref: "projection:hash-1",
      completeness: "complete" as const,
      asOf: "2026-09-11T08:00:00Z",
      outputHash: "hash-1",
      limitations: [],
    },
    narrative: {
      summary: "A100 在 1000 工厂可用库存 42 KG，在途 100 KG，供应充足。",
      limitations: [],
      evidenceRefs: ["fact:inv-1", "fact:po-1"],
    },
    limitations: [],
  };
}

async function startFixtureServer(handler: (body: unknown) => unknown): Promise<{ server: Server; baseUrl: string; requests: unknown[] }> {
  const requests: unknown[] = [];
  const server = createServer((req, res) => {
    if (req.method !== "POST" || req.url !== "/api/semantic-tools") {
      res.writeHead(404).end();
      return;
    }
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    req.on("end", () => {
      const body = JSON.parse(raw) as unknown;
      requests.push(body);
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(handler(body)));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as AddressInfo).port;
  return { server, baseUrl: `http://127.0.0.1:${port}`, requests };
}

describe("sap-nexus dsh tool round trip", () => {
  let server: Server | undefined;

  afterEach(async () => {
    await server?.close();
    server = undefined;
  });

  it("drives one model-selected tool call through the facade and presents the result", async () => {
    const fixture = await startFixtureServer(() => cannedFacadeResponse());
    server = fixture.server;

    const ctx = await mountSpine(new Context(), { defaultModel: { provider: PROVIDER, model: MODEL } });
    ctx.llm.registerAdapter([PROVIDER], new MockAdapter([
      toolCallResponse("call-1", "diagnose_material_supply", {
        utterance: "A100 在 1000 工厂够不够用、在途多少？",
        material: "A100",
        plant: "1000",
      }),
      textResponse("结论：A100 在 1000 工厂可用 42 KG，在途 100 KG。"),
    ]));
    registerSapNexusTool(ctx, { facadeUrl: fixture.baseUrl });

    const result = await runTurn(ctx, {
      task: "A100 在 1000 工厂够不够用、在途多少？",
      provider: PROVIDER,
      model: MODEL,
    });

    expect(fixture.requests).toHaveLength(1);
    const body = fixture.requests[0] as Record<string, unknown>;
    expect(body).toMatchObject({
      contractVersion: 1,
      tool: "diagnose_material_supply",
      utterance: "A100 在 1000 工厂够不够用、在途多少？",
      slots: { material: "A100", plant: "1000" },
    });
    expect(body).not.toHaveProperty("rfcName");
    expect(body).not.toHaveProperty("bindingId");
    expect(result.output).toContain("42 KG");
    result.dispose();
  }, 30_000);

  it("surfaces non-complete facade status without inventing values", async () => {
    const response = cannedFacadeResponse();
    response.status = "clarification";
    response.projection = undefined;
    response.facts = [];
    response.capabilityChain = [];
    response.narrative = { summary: "请提供工厂编码。", limitations: [] };
    const fixture = await startFixtureServer(() => response);
    server = fixture.server;

    const ctx = await mountSpine(new Context(), { defaultModel: { provider: PROVIDER, model: MODEL } });
    ctx.llm.registerAdapter([PROVIDER], new MockAdapter([
      toolCallResponse("call-1", "diagnose_material_supply", {
        utterance: "物料够不够用？",
      }),
      textResponse("需要先澄清工厂。"),
    ]));
    registerSapNexusTool(ctx, { facadeUrl: fixture.baseUrl });

    const result = await runTurn(ctx, {
      task: "物料够不够用？",
      provider: PROVIDER,
      model: MODEL,
    });
    expect(result.output).toContain("需要先澄清工厂");
    result.dispose();
  }, 30_000);

  it("rejects malformed tool arguments at the local pre-execute gate", async () => {
    const fixture = await startFixtureServer(() => cannedFacadeResponse());
    server = fixture.server;

    const ctx = await mountSpine(new Context(), { defaultModel: { provider: PROVIDER, model: MODEL } });
    ctx.llm.registerAdapter([PROVIDER], new MockAdapter([
      toolCallResponse("call-1", "diagnose_material_supply", { wrong: 1 }),
      textResponse("工具参数被拒绝。"),
    ]));
    registerSapNexusTool(ctx, { facadeUrl: fixture.baseUrl });

    const result = await runTurn(ctx, {
      task: "随便问点什么",
      provider: PROVIDER,
      model: MODEL,
    });
    expect(fixture.requests).toHaveLength(0);
    expect(result.output).toContain("拒绝");
    result.dispose();
  }, 30_000);
});

describe("harness architectural guard", () => {
  it("plugin metadata is a named dsh plugin", () => {
    expect(pluginName).toBe("sap-nexus-tools");
  });
});
