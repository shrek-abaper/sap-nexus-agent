import { describe, expect, it } from "vitest";
import type { StreamChunk } from "@deepseek-ai/dsh-llm";
import { OpenAiCompatibleAdapter } from "./openai-compatible-adapter";

function sse(frames: string[]): Response {
  const body = frames.map((frame) => `data: ${frame}\n\n`).join("") + "data: [DONE]\n\n";
  return new Response(body, { status: 200 });
}

function delta(payload: object): string {
  return JSON.stringify({ choices: [{ delta: payload }] });
}

async function collect(frames: string[]): Promise<StreamChunk[]> {
  const adapter = new OpenAiCompatibleAdapter({
    baseUrl: "https://example.test",
    apiKey: "k",
    model: "m",
    fetchImpl: (async () => sse(frames)) as unknown as typeof fetch,
  });
  const chunks: StreamChunk[] = [];
  for await (const chunk of adapter.stream({ messages: [] } as never)) {
    chunks.push(chunk);
  }
  return chunks;
}

describe("OpenAiCompatibleAdapter streaming", () => {
  it("streams content token-by-token as one text block", async () => {
    const chunks = await collect([delta({ content: "计划：" }), delta({ content: "先查库存" })]);
    expect(chunks.map((chunk) => chunk.type)).toEqual([
      "block-start",
      "text-delta",
      "text-delta",
      "block-end",
      "usage",
      "finish",
    ]);
    expect(chunks[0]).toMatchObject({ blockType: "text", index: 0 });
    expect(chunks[3]).toMatchObject({ block: { type: "text", text: "计划：先查库存" } });
  });

  it("maps reasoning_content into a reasoning block ahead of the text block", async () => {
    const chunks = await collect([
      delta({ reasoning_content: "用户要查库存" }),
      delta({ reasoning_content: "，先诊断" }),
      delta({ content: "计划：先查" }),
    ]);
    expect(chunks.map((chunk) => chunk.type)).toEqual([
      "block-start",
      "reasoning-delta",
      "reasoning-delta",
      "block-end",
      "block-start",
      "text-delta",
      "block-end",
      "usage",
      "finish",
    ]);
    expect(chunks[0]).toMatchObject({ blockType: "reasoning", index: 0 });
    expect(chunks[3]).toMatchObject({ block: { type: "reasoning", text: "用户要查库存，先诊断" } });
    expect(chunks[4]).toMatchObject({ blockType: "text", index: 1 });
  });

  it("closes the text block, then streams a tool-call block to a tool-calls finish", async () => {
    const chunks = await collect([
      delta({ content: "计划：查库存" }),
      delta({ tool_calls: [{ index: 0, id: "call-1", function: { name: "diagnose_material_supply", arguments: "" } }] }),
      delta({ tool_calls: [{ index: 0, function: { arguments: "{\"material\":\"DEMOA1\"" } }] }),
      delta({ tool_calls: [{ index: 0, function: { arguments: "}" } }] }),
      JSON.stringify({ choices: [{ delta: {}, finish_reason: "tool_calls" }] }),
    ]);
    const types = chunks.map((chunk) => chunk.type);
    expect(types).toEqual([
      "block-start",
      "text-delta",
      "block-end",
      "block-start",
      "tool-call-delta",
      "tool-call-delta",
      "block-end",
      "usage",
      "finish",
    ]);
    expect(chunks[6]).toMatchObject({
      block: { type: "tool-call", id: "call-1", name: "diagnose_material_supply", arguments: "{\"material\":\"DEMOA1\"}" },
    });
    expect(chunks[8]).toMatchObject({ reason: { kind: "tool-calls" } });
  });

  it("emits only usage+finish for an empty response", async () => {
    const chunks = await collect([delta({})]);
    expect(chunks.map((chunk) => chunk.type)).toEqual(["usage", "finish"]);
  });
});
