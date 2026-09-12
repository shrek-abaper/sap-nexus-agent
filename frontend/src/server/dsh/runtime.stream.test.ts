import { afterEach, describe, expect, it } from "vitest";
import {
  LlmAdapter,
  ToolCallId,
  type GenerateOptions,
  type LlmResolvedModelInfo,
  type StreamChunk,
} from "@deepseek-ai/dsh-llm";
import type { SemanticToolResponse } from "../../runtime/semantic-tools/types";
import { createDshRuntime, type DshRuntime, type ToolHandler } from "./runtime";

function textDelta(text: string): StreamChunk[] {
  return [
    { type: "block-start", index: 0, blockType: "text" },
    { type: "text-delta", index: 0, text },
    { type: "block-end", index: 0, block: { type: "text", text } },
    { type: "usage", usage: { inputTokens: 1, outputTokens: 1 } },
    { type: "finish", reason: { kind: "stop" } },
  ];
}

function toolCallResponse(name: string, args: object): StreamChunk[] {
  const id = ToolCallId("c1");
  const json = JSON.stringify(args);
  return [
    { type: "block-start", index: 0, blockType: "tool-call" },
    { type: "tool-call-delta", index: 0, id, name, argumentsDelta: json },
    { type: "block-end", index: 0, block: { type: "tool-call", id, name, arguments: json } },
    { type: "usage", usage: { inputTokens: 1, outputTokens: 1 } },
    { type: "finish", reason: { kind: "tool-calls" } },
  ];
}

class ScriptedAdapter extends LlmAdapter {
  constructor(private readonly script: StreamChunk[][]) { super(); }
  override resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
    return Promise.resolve({ provider, id: model, name: model });
  }
  async *stream(): AsyncIterable<StreamChunk> {
    const chunks = this.script.shift();
    if (!chunks) throw new Error("script exhausted");
    for (const chunk of chunks) yield chunk;
  }
}

describe("in-process dsh streaming", () => {
  let runtime: DshRuntime | undefined;
  afterEach(async () => { await runtime?.dispose(); runtime = undefined; });

  it("emits token deltas for a plain answer then final", async () => {
    runtime = await createDshRuntime({
      provider: "test", model: "mock",
      adapter: new ScriptedAdapter([textDelta("你好世界")]),
      handlers: {},
    });
    const events: string[] = [];
    for await (const event of runtime.streamMessage("c1", "hi")) {
      events.push(event.type);
      if (event.type === "delta") expect(event.phase).toBe("answer");
    }
    expect(events).toContain("delta");
    expect(events.at(-1)).toBe("final");
  });

  it("emits tool-start/tool-result with structured result and collapses at final", async () => {
    const response: SemanticToolResponse = {
      contractVersion: 2,
      tool: "diagnose_material_supply",
      status: "complete",
      runId: "run-1",
      resolved: { semanticValues: [] },
      capabilityChain: [{ capabilityId: "MM.Inventory.GetAvailability", state: "succeeded" }],
      facts: [],
      narrative: { summary: "12 EA", limitations: [] },
      limitations: [],
    };
    const handler: ToolHandler = async () => response;
    runtime = await createDshRuntime({
      provider: "test", model: "mock",
      adapter: new ScriptedAdapter([
        toolCallResponse("diagnose_material_supply", { utterance: "x" }),
        textDelta("最终答案"),
      ]),
      handlers: { diagnose_material_supply: handler },
    });

    const seen: Record<string, number> = {};
    let finalOutput = "";
    let sawAnswerDelta = false;
    for await (const event of runtime.streamMessage("c2", "x")) {
      seen[event.type] = (seen[event.type] ?? 0) + 1;
      // The post-tool text delta is the visible answer phase.
      if (event.type === "delta" && event.phase === "answer") sawAnswerDelta = true;
      if (event.type === "tool-start") expect(event.name).toBe("diagnose_material_supply");
      if (event.type === "tool-result") {
        expect(event.callId).toBe("c1");
        expect(event.result?.status).toBe("complete");
      }
      if (event.type === "final") finalOutput = event.output;
    }
    expect(seen["tool-start"]).toBe(1);
    expect(seen["tool-result"]).toBe(1);
    expect(sawAnswerDelta).toBe(true);
    expect(finalOutput).toContain("最终答案");
  });
});
