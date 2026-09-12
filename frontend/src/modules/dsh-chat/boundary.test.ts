import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const dir = import.meta.dirname;

describe("dsh client/server boundary", () => {
  it("the dsh chat UI never imports the server dsh runtime or @deepseek packages", () => {
    for (const file of ["DshChat.tsx", "ToolCallCard.tsx", "types.ts"]) {
      const text = readFileSync(join(dir, file), "utf8");
      expect(text, file).not.toMatch(/from ["']@deepseek\/(cordis|dsh-)/);
      expect(text, file).not.toMatch(/import .*server\/dsh|openai-compatible-adapter/);
    }
  });

  it("WRITE decisions go through the agent-runs approval route, not a dsh-local gate", () => {
    const card = readFileSync(join(dir, "ToolCallCard.tsx"), "utf8");
    expect(card).toMatch(/\/api\/agent-runs\/.*\/approval/);
    expect(card).not.toMatch(/\/capabilities\/.*\/(approve|execute)/);
  });

  it("the in-process registry is server-only", () => {
    const registry = readFileSync(join(dir, "..", "..", "server", "dsh", "registry.ts"), "utf8");
    expect(registry).toMatch(/import "server-only"/);
    // Tools reach the governed layer through executeSemanticTool, never HTTP self-call.
    expect(registry).not.toMatch(/fetch\(/);
  });
});
