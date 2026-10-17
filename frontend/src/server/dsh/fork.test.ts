import { describe, expect, it } from "vitest";
import {
  LlmAdapter,
  type GenerateOptions,
  type LlmResolvedModelInfo,
  type StreamChunk,
} from "@deepseek-ai/dsh-llm";
import { createDshRuntime, DshForkError, sliceCompletedTurnPrefix } from "./runtime";

function textResponse(text: string): StreamChunk[] {
  return [
    { type: "block-start", index: 0, blockType: "text" },
    { type: "text-delta", index: 0, text },
    { type: "block-end", index: 0, block: { type: "text", text } },
    { type: "usage", usage: { inputTokens: 10, outputTokens: text.length } },
    { type: "finish", reason: { kind: "stop" } },
  ];
}

class FakeAdapter extends LlmAdapter {
  constructor(private readonly reply: string) {
    super();
  }
  override resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
    return Promise.resolve({ provider, id: model, name: model });
  }
  async *stream(_options: GenerateOptions): AsyncIterable<StreamChunk> {
    yield* textResponse(this.reply);
  }
}

describe("sliceCompletedTurnPrefix", () => {
  const events = [
    { type: "session/created" },
    { type: "turn/start" },
    { type: "user/message" },
    { type: "assistant/message" },
    { type: "turn/end" },
    { type: "turn/start" },
    { type: "user/message" },
    { type: "assistant/attempt" },
    { type: "assistant/message" },
    { type: "turn/end" },
  ];

  it("slices right after the Nth turn/end", () => {
    expect(sliceCompletedTurnPrefix(events, 1)).toHaveLength(5);
    expect(sliceCompletedTurnPrefix(events, 2)).toHaveLength(10);
  });

  it("returns null when fewer completed turns exist", () => {
    expect(sliceCompletedTurnPrefix(events, 3)).toBeNull();
    expect(sliceCompletedTurnPrefix(events.slice(0, 4), 1)).toBeNull();
  });
});

describe("runtime forkSession", () => {
  it("carries the parent turn into the forked session's LLM context", async () => {
    const captured: string[] = [];
    class CapturingAdapter extends LlmAdapter {
      override resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
        return Promise.resolve({ provider, id: model, name: model });
      }
      async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
        captured.push(JSON.stringify(options.messages ?? []));
        yield* textResponse("分叉回答");
      }
    }
    const runtime = await createDshRuntime({
      provider: "fake",
      model: "fake-model",
      adapter: new CapturingAdapter(),
      handlers: {},
    });
    try {
      await runtime.sendMessage("conv-parent", "DEMOA1 在 1000 的库存");
      await runtime.forkSession("conv-parent", 1, "conv-child");
      await runtime.sendMessage("conv-child", "在途呢？");
      const childCall = captured[1];
      expect(childCall).toContain("DEMOA1 在 1000 的库存");
      expect(childCall).toContain("分叉回答");
      expect(childCall).toContain("在途呢？");
    } finally {
      await runtime.dispose();
    }
  });

  it("forks a live session and the fork answers independently", async () => {
    const runtime = await createDshRuntime({
      provider: "fake",
      model: "fake-model",
      adapter: new FakeAdapter("分叉回答"),
      handlers: {},
    });
    try {
      await runtime.sendMessage("conv-parent", "第一个问题");
      await runtime.forkSession("conv-parent", 1, "conv-child");
      const turn = await runtime.sendMessage("conv-child", "接着问");
      expect(turn.output).toBe("分叉回答");
    } finally {
      await runtime.dispose();
    }
  });

  it("rejects fork when the parent session is not live", async () => {
    const runtime = await createDshRuntime({
      provider: "fake",
      model: "fake-model",
      adapter: new FakeAdapter("ok"),
      handlers: {},
    });
    try {
      await expect(runtime.forkSession("conv-missing", 1, "conv-child")).rejects.toMatchObject({
        code: "PARENT_NOT_LIVE",
      });
      await expect(runtime.forkSession("conv-missing", 1, "conv-child")).rejects.toBeInstanceOf(DshForkError);
    } finally {
      await runtime.dispose();
    }
  });

  it("rejects fork beyond the parent's completed turns", async () => {
    const runtime = await createDshRuntime({
      provider: "fake",
      model: "fake-model",
      adapter: new FakeAdapter("ok"),
      handlers: {},
    });
    try {
      await runtime.sendMessage("conv-parent", "只有一轮");
      await expect(runtime.forkSession("conv-parent", 99, "conv-child")).rejects.toMatchObject({
        code: "PREFIX_UNBALANCED",
      });
    } finally {
      await runtime.dispose();
    }
  });
});
