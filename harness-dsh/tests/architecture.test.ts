import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

// Architectural red lines (Notion v1.0 §5): the dsh layer must not reach the
// Java Gateway directly and must not carry RFC/binding/credential material.
const SRC_DIR = join(import.meta.dirname, "..", "src");
const CONFIG_DIR = join(import.meta.dirname, "..", "config");

function listTsFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    return entry.isDirectory() ? listTsFiles(full) : (entry.name.endsWith(".ts") ? [full] : []);
  });
}

describe("harness-only red lines", () => {
  it("no source file calls the Java Gateway surface or names an RFC/binding", () => {
    for (const file of listTsFiles(SRC_DIR)) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(/\/capabilities\//);
      expect(text, file).not.toMatch(/BAPI_|RFC_NAME|rfcName|bindingId/);
      expect(text, file).not.toMatch(/approve|\/execute/);
    }
  });

  it("the only outbound HTTP target is the semantic tool facade", () => {
    const client = readFileSync(join(SRC_DIR, "facade-client.ts"), "utf8");
    expect(client).toMatch(/\/api\/semantic-tools/);
    const matches = client.match(/fetch\(/g) ?? [];
    expect(matches).toHaveLength(1);
  });

  it("bundle config registers exactly one business tool and no coding surfaces", () => {
    const bundle = readFileSync(join(CONFIG_DIR, "cordis.bundle.patch.yml"), "utf8");
    expect(bundle).toContain("diagnose_material_supply");
    expect(bundle).not.toMatch(/dsh-tool-bash|dsh-tool-fs|dsh-tool-subagent|dsh-tool-workflow/);
  });

  it("committed config contains no inline credentials", () => {
    for (const name of ["cordis.yml", "cordis.bundle.patch.yml", "cordis.patch.yml"]) {
      const text = readFileSync(join(CONFIG_DIR, name), "utf8");
      expect(text, name).not.toMatch(/sk-[A-Za-z0-9]{8,}/);
      expect(text, name).not.toMatch(/api[_-]?key\s*[:=]\s*["']?[A-Za-z0-9]{12,}/i);
    }
  });
});
