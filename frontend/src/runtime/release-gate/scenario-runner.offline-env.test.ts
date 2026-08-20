import { describe, expect, it, vi } from "vitest";
import path from "node:path";
import { EventEmitter } from "node:events";

const { spawnCalls } = vi.hoisted(() => ({
  spawnCalls: [] as { command: string; args: string[]; env?: NodeJS.ProcessEnv }[],
}));

vi.mock("node:child_process", () => ({
  spawn: (command: string, args: string[], options: { env?: NodeJS.ProcessEnv }) => {
    spawnCalls.push({ command, args, env: options?.env });
    const child = new EventEmitter() as EventEmitter & { stdout: EventEmitter; stderr: EventEmitter };
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    // Non-zero exit keeps the scenario runner on its "no evidence" path: this pin
    // only inspects how the child was launched, never what it produced.
    setImmediate(() => { child.emit("close", 1); });
    return child;
  },
}));

const { runOfflineReleaseScenarios } = await import("./scenario-runner");

const repoRoot = path.resolve(process.cwd(), "..");

describe("offline release scenario subprocesses", () => {
  it("blanks LLM credentials for every spawned eval so the gate stays off the network", async () => {
    await runOfflineReleaseScenarios({
      repoRoot,
      now: "2026-08-05T01:00:00.000Z",
      target: "L1",
    });

    expect(spawnCalls.length).toBeGreaterThan(0);
    for (const call of spawnCalls) {
      expect(call.env?.LLM_API_KEY).toBe("");
      expect(call.env?.LLM_BASE_URL).toBe("");
      // The rest of the parent environment must still reach the child.
      expect(call.env?.PATH).toBe(process.env.PATH);
    }
  });
});
