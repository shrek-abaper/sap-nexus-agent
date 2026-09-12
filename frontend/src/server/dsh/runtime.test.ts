import { describe, expect, it, afterEach } from "vitest";
import {
  LlmAdapter,
  ToolCallId,
  type GenerateOptions,
  type LlmResolvedModelInfo,
  type StreamChunk,
} from "@deepseek-ai/dsh-llm";
import type { SemanticToolResponse } from "../../runtime/semantic-tools/types";
import { createDshRuntime, type DshRuntime, type ToolHandler } from "./runtime";

function textResponse(text: string): StreamChunk[] {
  return [
    { type: "block-start", index: 0, blockType: "text" },
    { type: "text-delta", index: 0, text },
    { type: "block-end", index: 0, block: { type: "text", text } },
    { type: "usage", usage: { inputTokens: 10, outputTokens: text.length } },
    { type: "finish", reason: { kind: "stop" } },
  ];
}

function toolCallResponse(name: string, args: object, text?: string): StreamChunk[] {
  const id = ToolCallId("call-1");
  const json = JSON.stringify(args);
  const chunks: StreamChunk[] = [];
  let index = 0;
  if (text) {
    chunks.push(
      { type: "block-start", index, blockType: "text" },
      { type: "text-delta", index, text },
      { type: "block-end", index, block: { type: "text", text } },
    );
    index += 1;
  }
  chunks.push(
    { type: "block-start", index, blockType: "tool-call" },
    { type: "tool-call-delta", index, id, name, argumentsDelta: json },
    { type: "block-end", index, block: { type: "tool-call", id, name, arguments: json } },
    { type: "usage", usage: { inputTokens: 10, outputTokens: 5 } },
    { type: "finish", reason: { kind: "tool-calls" } },
  );
  return chunks;
}

class ScriptedAdapter extends LlmAdapter {
  constructor(private readonly script: StreamChunk[][]) {
    super();
  }
  override resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
    return Promise.resolve({ provider, id: model, name: model });
  }
  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    const chunks = this.script.shift();
    if (!chunks) throw new Error("script exhausted");
    for (const chunk of chunks) {
      void options;
      yield chunk;
    }
  }
}

function canned(status: SemanticToolResponse["status"], summary: string): SemanticToolResponse {
  return {
    contractVersion: 2,
    tool: "diagnose_material_supply",
    status,
    runId: "run-x",
    resolved: { semanticValues: [] },
    capabilityChain: [],
    facts: [],
    narrative: { summary, limitations: [] },
    limitations: [],
  };
}

describe("in-process dsh runtime", () => {
  let runtime: DshRuntime | undefined;

  afterEach(async () => {
    await runtime?.dispose();
    runtime = undefined;
  });

  it("routes a model-selected tool call through the injected governed handler", async () => {
    const calls: Array<{ name: string; args: unknown }> = [];
    const handler: ToolHandler = async (args) => {
      calls.push({ name: "diagnose_material_supply", args });
      return canned("complete", "DEMOA1 在 1000 工厂可用 12 EA。");
    };

    runtime = await createDshRuntime({
      provider: "test",
      model: "mock",
      adapter: new ScriptedAdapter([
        toolCallResponse("diagnose_material_supply", {
          utterance: "DEMOA1 在 1000 够不够",
          material: "DEMOA1",
          plant: "1000",
        }),
        textResponse("结论：可用 12 EA。"),
      ]),
      handlers: { diagnose_material_supply: handler },
    });

    const turn = await runtime.sendMessage("conv-1", "DEMOA1 在 1000 够不够");
    expect(calls).toHaveLength(1);
    expect(calls[0].args).toMatchObject({ material: "DEMOA1", plant: "1000" });
    expect(turn.toolCalls).toHaveLength(1);
    expect(turn.toolCalls[0].status).toBe("completed");
    expect(turn.output).toContain("12 EA");
  });

  it("marks an awaiting_approval WRITE handler result and keeps multi-turn context", async () => {
    const proposal: SemanticToolResponse = {
      ...canned("awaiting_approval", "待审批提案"),
      tool: "propose_replenishment",
      approval: {
        approvalId: "appr-1",
        runId: "run-1",
        expiresAt: "2026-09-12T10:00:00.000Z",
        capabilityId: "MM.PR.CreateDraft",
        parameters: {
          material: "DEMOA1", plant: "1000", quantity: "3",
          unit: "EA", delivery_date: "2026-09-20", purchasing_group: "601",
        },
        factRefs: ["fact:1"],
        hashes: { subjectHash: "s", proposalHash: "p", parameterSnapshotHash: "h" },
      },
    };

    runtime = await createDshRuntime({
      provider: "test",
      model: "mock",
      adapter: new ScriptedAdapter([
        toolCallResponse("propose_replenishment", {
          utterance: "补 3 个", material: "DEMOA1", plant: "1000",
          requiredQuantity: 10, targetDate: "2026-09-20", purchasingGroup: "601",
        }),
        textResponse("已生成提案，请在卡片审批。"),
        textResponse("第二条消息，无需工具。"),
      ]),
      handlers: { propose_replenishment: async () => proposal },
    });

    const first = await runtime.sendMessage("conv-w", "补 3 个");
    expect(first.toolCalls[0].status).toBe("awaiting_approval");
    expect(first.toolCalls[0].result?.approval?.approvalId).toBe("appr-1");

    const second = await runtime.sendMessage("conv-w", "再说一句");
    expect(second.output).toContain("第二条消息");
  });
});
