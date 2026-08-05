import { spawnSync } from "node:child_process";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("release gate CLI entrypoint", () => {
  it("executes under vite-node and returns usage failure for an invalid profile", () => {
    const result = spawnSync(
      path.join(process.cwd(), "node_modules/.bin/vite-node"),
      ["src/runtime/release-gate/cli.ts", "--profile", "invalid"],
      { cwd: process.cwd(), encoding: "utf8" },
    );

    expect(result.status).toBe(2);
  });
});
