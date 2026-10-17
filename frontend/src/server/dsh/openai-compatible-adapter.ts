import {
  LlmAdapter,
  ToolCallId,
  type GenerateOptions,
  type LlmResolvedModelInfo,
  type StreamChunk,
  type Message,
} from "@deepseek-ai/dsh-llm";

// Thin OpenAI-compatible chat-completions adapter (DeepSeek function-calling).
// Kept server-only: the API key lives in the Next server environment and never
// reaches the browser. Streams are accumulated per block and replayed as dsh
// chunks; correctness matters more than token-level streaming for this app.
export type OpenAiCompatibleConfig = {
  baseUrl: string;
  apiKey: string;
  model: string;
  fetchImpl?: typeof fetch;
};

type Delta = {
  content?: string | null;
  reasoning_content?: string | null;
  tool_calls?: Array<{
    index?: number;
    id?: string;
    type?: "function";
    function?: { name?: string; arguments?: string };
  }>;
};

type ContentBlock = { type: string; text?: string; toolCallId?: string } & Record<string, unknown>;

function textOfBlocks(blocks: ContentBlock[]): string {
  return blocks
    .filter((block) => block.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("");
}

export function toWireMessages(messages: Message[], system?: string) {
  const wire: Array<Record<string, unknown>> = [];
  if (system) wire.push({ role: "system", content: system });
  for (const message of messages) {
    const role = (message as { role?: string }).role;
    const sourceKind = (message as { source?: { kind?: string } }).source?.kind;
    const rawContent = (message as { content?: unknown }).content;

    // dsh models a tool result as role:"user" + source.kind:"tool", whose
    // content is one ToolResultBlock (toolCallId + inner text blocks). It is
    // NOT role:"tool". Map it to the OpenAI tool message so the model sees
    // the deterministic result text paired with its tool_call_id.
    if (sourceKind === "tool") {
      const block = Array.isArray(rawContent)
        ? (rawContent as ContentBlock[]).find((item) => item.type === "tool-result")
        : undefined;
      const toolCallId = block?.toolCallId ?? (message as { toolCallId?: string }).toolCallId;
      wire.push({
        role: "tool",
        tool_call_id: toolCallId,
        content: block ? blocksToText(block.content) : toolResultToText(rawContent),
      });
      continue;
    }

    // dsh assistant/user messages carry ContentBlock[]: text blocks plus
    // tool-call blocks. Normalize to OpenAI wire form (content + tool_calls);
    // emitting the raw block JSON as content makes the model misread its own
    // history as an anomaly and retry tools that already succeeded.
    const blocks: ContentBlock[] = [];
    let textContent = "";
    if (typeof rawContent === "string") {
      textContent = rawContent;
    } else if (Array.isArray(rawContent)) {
      for (const block of rawContent as ContentBlock[]) {
        if (block && typeof block === "object") blocks.push(block);
      }
      textContent = textOfBlocks(blocks);
    }

    const toolCalls = blocks
      .filter((block) => block.type === "tool-call")
      .map((block) => {
        const args = block.arguments;
        return {
          id: String(block.id ?? ""),
          type: "function" as const,
          function: {
            name: String(block.name ?? ""),
            arguments: typeof args === "string" ? args : JSON.stringify(args ?? {}),
          },
        };
      });

    if (role === "assistant" && toolCalls.length > 0) {
      wire.push({ role: "assistant", content: textContent, tool_calls: toolCalls });
      continue;
    }
    wire.push({ role: role ?? "user", content: textContent });
  }
  return wire;
}

function blocksToText(content: unknown): string {
  if (Array.isArray(content)) {
    return textOfBlocks(content as ContentBlock[]);
  }
  return content == null ? "" : String(content);
}

// ToolResultMessage.content is a single ToolResultBlock whose own `content`
// holds the text blocks; unwrap both forms.
function toolResultToText(content: unknown): string {
  if (Array.isArray(content)) {
    const blocks = content as ContentBlock[];
    const inner = blocks.find((block) => block.type === "tool-result");
    if (inner) return blocksToText(inner.content);
    return blocksToText(blocks);
  }
  return blocksToText(content);
}

export class OpenAiCompatibleAdapter extends LlmAdapter {
  constructor(private readonly config: OpenAiCompatibleConfig) {
    super();
  }

  override resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
    return Promise.resolve({ provider, id: model, name: model });
  }

  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    const fetchImpl = this.config.fetchImpl ?? fetch;
    const url = this.config.baseUrl.replace(/\/+$/, "") + "/chat/completions";
    const response = await fetchImpl(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "authorization": `Bearer ${this.config.apiKey}`,
      },
      body: JSON.stringify({
        model: this.config.model,
        messages: toWireMessages(options.messages, options.system),
        tools: options.tools?.map((tool) => ({
          type: "function",
          function: { name: tool.name, description: tool.description, parameters: tool.parameters },
        })),
        tool_choice: options.tools && options.tools.length > 0 ? "auto" : undefined,
        temperature: options.temperature ?? 0,
        stream: true,
      }),
      signal: options.signal,
    });

    if (!response.ok || !response.body) {
      const text = await response.text().catch(() => "");
      throw new Error(`LLM HTTP ${response.status}: ${text.slice(0, 300)}`);
    }

    // Token-level streaming with block lifecycle: reasoning (if the model
    // emits reasoning_content) -> text -> tool-call blocks, closed in that
    // order. dsh requires block-start before deltas and block-end before
    // finish, so every open block is closed before the next one opens and
    // at end of stream.
    let finishReason: "stop" | "tool-calls" = "stop";
    let outputChars = 0;
    let nextIndex = 0;
    let openText: { index: number; blockType: "reasoning" | "text"; text: string } | null = null;
    let openCall: { index: number; seq: number; id: string; name: string; args: string } | null = null;

    function* closeText(): Generator<StreamChunk> {
      if (!openText) return;
      yield {
        type: "block-end",
        index: openText.index,
        block: { type: openText.blockType, text: openText.text },
      } as StreamChunk;
      openText = null;
    }
    function* closeCall(): Generator<StreamChunk> {
      if (!openCall) return;
      const id = ToolCallId(openCall.id || `call-${Math.random().toString(36).slice(2)}`);
      yield {
        type: "block-end",
        index: openCall.index,
        block: { type: "tool-call", id, name: openCall.name, arguments: openCall.args },
      } as StreamChunk;
      openCall = null;
    }
    function* openBlock(blockType: "reasoning" | "text"): Generator<StreamChunk, { index: number }> {
      yield* closeCall();
      yield* closeText();
      const index = nextIndex++;
      yield { type: "block-start", index, blockType } as StreamChunk;
      return { index };
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const payload = trimmed.slice(5).trim();
        if (payload === "[DONE]") continue;
        let parsed: { choices?: Array<{ delta?: Delta; finish_reason?: string | null }>; usage?: { total_tokens?: number } };
        try {
          parsed = JSON.parse(payload);
        } catch {
          continue;
        }
        const choice = parsed.choices?.[0];
        if (!choice) continue;

        const reasoningDelta = choice.delta?.reasoning_content;
        if (reasoningDelta) {
          if (!openText || openText.blockType !== "reasoning") {
            const { index } = yield* openBlock("reasoning");
            openText = { index, blockType: "reasoning", text: "" };
          }
          openText.text += reasoningDelta;
          yield { type: "reasoning-delta", index: openText.index, text: reasoningDelta } as StreamChunk;
        }

        const contentDelta = choice.delta?.content;
        if (contentDelta) {
          if (!openText || openText.blockType !== "text") {
            const { index } = yield* openBlock("text");
            openText = { index, blockType: "text", text: "" };
          }
          openText.text += contentDelta;
          outputChars += contentDelta.length;
          yield { type: "text-delta", index: openText.index, text: contentDelta } as StreamChunk;
        }

        for (const call of choice.delta?.tool_calls ?? []) {
          const seq = call.index ?? 0;
          if (!openCall || openCall.seq !== seq) {
            yield* closeCall();
            yield* closeText();
            const index = nextIndex++;
            yield { type: "block-start", index, blockType: "tool-call" } as StreamChunk;
            openCall = { index, seq, id: "", name: "", args: "" };
          }
          if (call.id) openCall.id = call.id;
          if (call.function?.name) openCall.name = call.function.name;
          const argsDelta = call.function?.arguments ?? "";
          if (argsDelta) {
            openCall.args += argsDelta;
            yield {
              type: "tool-call-delta",
              index: openCall.index,
              id: ToolCallId(openCall.id || `call-pending-${openCall.seq}`),
              name: openCall.name,
              argumentsDelta: argsDelta,
            } as StreamChunk;
          }
        }
        if (choice.finish_reason === "tool_calls") finishReason = "tool-calls";
      }
    }

    yield* closeText();
    yield* closeCall();
    yield { type: "usage", usage: { inputTokens: 0, outputTokens: outputChars } };
    yield { type: "finish", reason: { kind: finishReason } };
  }
}
