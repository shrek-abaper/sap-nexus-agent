import {
  LlmAdapter,
  ToolCallId,
  type GenerateOptions,
  type LlmResolvedModelInfo,
  type StreamChunk,
} from "@deepseek-ai/dsh-llm";

export function textResponse(text: string): StreamChunk[] {
  return [
    { type: "block-start", index: 0, blockType: "text" },
    { type: "text-delta", index: 0, text },
    { type: "block-end", index: 0, block: { type: "text", text } },
    { type: "usage", usage: { inputTokens: 10, outputTokens: text.length } },
    { type: "finish", reason: { kind: "stop" } },
  ];
}

export function toolCallResponse(
  rawCallId: string,
  name: string,
  args: object,
  text?: string,
): StreamChunk[] {
  const callId = ToolCallId(rawCallId);
  const argumentsJson = JSON.stringify(args);
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
    { type: "tool-call-delta", index, id: callId, name, argumentsDelta: argumentsJson },
    {
      type: "block-end",
      index,
      block: { type: "tool-call", id: callId, name, arguments: argumentsJson },
    },
    { type: "usage", usage: { inputTokens: 10, outputTokens: 5 } },
    { type: "finish", reason: { kind: "tool-calls" } },
  );
  return chunks;
}

// Scripted keyless adapter: each model call consumes the next response.
export class MockAdapter extends LlmAdapter {
  readonly requests: GenerateOptions[] = [];

  constructor(private readonly script: StreamChunk[][]) {
    super();
  }

  override resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
    return Promise.resolve({ provider, id: model, name: model });
  }

  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    this.requests.push(options);
    const chunks = this.script.shift();
    if (!chunks) throw new Error("MockAdapter: script exhausted");
    for (const chunk of chunks) {
      if (options.signal?.aborted) throw new Error("aborted");
      yield chunk;
    }
  }
}
