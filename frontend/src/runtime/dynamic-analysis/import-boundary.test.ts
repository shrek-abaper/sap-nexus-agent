import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

// dynamic-analysis must orchestrate PlanExecutor + the Python adapter only;
// it must not pull in composition/recommendation/projection/semantic-tools.
describe("dynamic-analysis import boundary", () => {
  const dir = path.dirname(new URL(import.meta.url).pathname);
  const files = readdirSync(dir).filter((f) => f.endsWith(".ts") && !f.endsWith(".test.ts"));

  it("imports neither composition, recommendation, projection, nor semantic-tools", () => {
    for (const file of files) {
      const source = readFileSync(path.join(dir, file), "utf8");
      expect(source).not.toContain("../composition");
      expect(source).not.toContain("../recommendation");
      expect(source).not.toContain("../projection");
      expect(source).not.toContain("../semantic-tools");
    }
  });
});
