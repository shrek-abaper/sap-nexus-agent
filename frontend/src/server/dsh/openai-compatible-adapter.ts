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
  tool_calls?: Array<{
    id?: string;
    type?: "function";
    function?: { name?: string; arguments?: string };
  }>;
};

function toWireMessages(messages: Message[], system?: string) {
  const wire: Array<Record<string, unknown>> = [];
  if (system) wire.push({ role: "system", content: system });
  for (const message of messages) {
    const role = (message as { role?: string }).role;
    const content = (message as { content?: unknown }).content;
    if (role === "tool") {
      wire.push({
        role: "tool",
        tool_call_id: (message as { toolCallId?: string }).toolCallId,
        content: typeof content === "string" ? content : JSON.stringify(content ?? ""),
      });
      continue;
    }
    const toolCalls = (message as { toolCalls?: unknown[] }).toolCalls;
    if (Array.isArray(toolCalls) && toolCalls.length > 0) {
      wire.push({
        role: role ?? "assistant",
        content: typeof content === "string" ? content : "",
        tool_calls: toolCalls.map((call) => {
          const c = call as { id?: string; name?: string; arguments?: unknown };
          return {
            id: c.id,
            type: "function",
            function: { name: c.name, arguments: typeof c.arguments === "string" ? c.arguments : JSON.stringify(c.arguments ?? {}) },
          };
        }),
      });
      continue;
    }
    wire.push({ role: role ?? "user", content: typeof content === "string" ? content : JSON.stringify(content ?? "") });
  }
  return wire;
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

    const textParts: string[] = [];
    const calls = new Map<number, { id: string; name: string; args: string }>();
    let finishReason: "stop" | "tool-calls" = "stop";

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
        if (choice.delta?.content) textParts.push(choice.delta.content);
        for (const call of choice.delta?.tool_calls ?? []) {
          const index = 0;
          const existing = calls.get(index) ?? { id: "", name: "", args: "" };
          if (call.id) existing.id = call.id;
          if (call.function?.name) existing.name = call.function.name;
          if (call.function?.arguments) existing.args += call.function.arguments;
          calls.set(index, existing);
        }
        if (choice.finish_reason === "tool_calls") finishReason = "tool-calls";
      }
    }

    let index = 0;
    const text = textParts.join("");
    if (text.length > 0) {
      yield { type: "block-start", index, blockType: "text" };
      yield { type: "text-delta", index, text };
      yield { type: "block-end", index, block: { type: "text", text } };
      index += 1;
    }
    for (const call of calls.values()) {
      if (!call.name) continue;
      const id = ToolCallId(call.id || `call-${Math.random().toString(36).slice(2)}`);
      yield { type: "block-start", index, blockType: "tool-call" };
      yield { type: "tool-call-delta", index, id, name: call.name, argumentsDelta: call.args };
      yield {
        type: "block-end",
        index,
        block: { type: "tool-call", id, name: call.name, arguments: call.args },
      };
      index += 1;
    }
    yield { type: "usage", usage: { inputTokens: 0, outputTokens: text.length } };
    yield { type: "finish", reason: { kind: finishReason } };
  }
}
