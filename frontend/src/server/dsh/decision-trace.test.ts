import { afterEach, describe, expect, it } from "vitest";

const previousTraceEnv = process.env.SAP_NEXUS_DECISION_TRACE;

afterEach(() => {
  // Restore rather than delete to avoid races with parallel test files.
  if (previousTraceEnv === undefined) {
    delete process.env.SAP_NEXUS_DECISION_TRACE;
  } else {
    process.env.SAP_NEXUS_DECISION_TRACE = previousTraceEnv;
  }
});
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { buildTraceRecord, recordDshTurn } from "./decision-trace";

let dirs: string[] = [];
function newDir(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "dsh-trace-"));
  dirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
});

const completedCall = {
  name: "diagnose_material_supply",
  args: { utterance: "q", material: "DEMOA1", plant: "1000", token: "SECRET" },
  status: "completed",
  result: {
    status: "complete",
    capabilityChain: [{ capabilityId: "MM.Inventory.GetAvailability", state: "executed" }],
  },
};

describe("buildTraceRecord", () => {
  it("maps a completed tool to SELECT with capability and filtered args", () => {
    const record = buildTraceRecord({
      conversationId: "c1",
      userText: "DEMOA1 在 1000 还有多少可用库存",
      toolCalls: [completedCall],
    });

    expect(record.decision).toBe("SELECT");
    expect(record.capabilityId).toBe("MM.Inventory.GetAvailability");
    expect(record.tool).toBe("diagnose_material_supply");
    expect(record.parameters).toEqual({ utterance: "q", material: "DEMOA1", plant: "1000" });
    expect(record.model).toBe("dsh");
    expect(String(record.utteranceHash)).not.toContain("DEMOA1");
  });

  it("maps clarification and rejected statuses", () => {
    const clarify = buildTraceRecord({
      conversationId: "c",
      userText: "查这个料",
      toolCalls: [{ result: { status: "clarification", capabilityChain: [] } }],
    });
    const rejected = buildTraceRecord({
      conversationId: "c",
      userText: "x",
      toolCalls: [{ result: { status: "failed", capabilityChain: [], error: { errorType: "E" } } }],
    });

    expect(clarify.decision).toBe("CLARIFY");
    expect(rejected.decision).toBe("REJECT");
    expect(rejected.errorType).toBe("E");
  });

  it("records null decision with an error event", () => {
    const record = buildTraceRecord({
      conversationId: "c",
      userText: "q",
      errorMessage: "boom",
    });

    expect(record.decision).toBeNull();
  });
});

describe("recordDshTurn", () => {
  it("appends one JSONL line to the configured path", () => {
    const target = path.join(newDir(), "nested/decisions.jsonl");
    process.env.SAP_NEXUS_DECISION_TRACE = target;

    recordDshTurn({ conversationId: "c1", userText: "查库存", toolCalls: [completedCall] });

    const lines = readFileSync(target, "utf8").trim().split("\n");
    expect(lines).toHaveLength(1);
    const record = JSON.parse(lines[0]);
    expect(record.schema).toBe("sap-nexus.decision-trace.v1");
    expect(record.conversationId).toBe("c1");
  });

  it("is a no-op when disabled", () => {
    process.env.SAP_NEXUS_DECISION_TRACE = "off";

    expect(() => recordDshTurn({ conversationId: "c", userText: "q" })).not.toThrow();
  });
});
