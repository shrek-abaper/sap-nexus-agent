import { describe, expect, it } from "vitest";
import { toWireMessages } from "./openai-compatible-adapter";

// Verifies the OpenAI-compatible wire normalization: dsh assistant messages
// carry ContentBlock[] (text + tool-call); they must become separate
// `content` text and a `tool_calls` array — never the raw block JSON.
describe("toWireMessages", () => {
  it("splits an assistant ContentBlock[] into content and tool_calls", () => {
    const wire = toWireMessages([
      {
        role: "assistant",
        content: [
          { type: "text", text: "好的，查询库存" },
          { type: "tool-call", id: "call-1", name: "diagnose_material_supply", arguments: '{"material":"P1"}' },
        ],
      },
      {
        // dsh models tool results as role user + source.kind tool.
        role: "user",
        source: { kind: "tool" },
        content: [{ type: "tool-result", toolCallId: "call-1", content: [{ type: "text", text: "事实: 26640 EA" }] }],
      },
    ] as never[]);

    const assistant = wire[0];
    expect(assistant).toMatchObject({ role: "assistant", content: "好的，查询库存" });
    expect(assistant.tool_calls).toEqual([
      { id: "call-1", type: "function", function: { name: "diagnose_material_supply", arguments: '{"material":"P1"}' } },
    ]);
    expect(assistant.content).not.toContain('"type":"tool-call"');

    const tool = wire[1];
    expect(tool.role).toBe("tool");
    expect(tool.tool_call_id).toBe("call-1");
    expect(tool.content).toBe("事实: 26640 EA");
  });
});
