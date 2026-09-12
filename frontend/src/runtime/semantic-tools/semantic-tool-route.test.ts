import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { POST } from "../../../app/api/semantic-tools/route";
import {
  resetAgentRunsForTests,
  resetAgentSessionsForTests,
  setAgentRunnerForTests,
  setDurableStoresForTests,
} from "../agent-runtime-adapter";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import { JsonlConversationStore } from "../durable/jsonl-conversation-store";
import type { WorkbenchOutcome } from "../durable/types";

describe("POST /api/semantic-tools", () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), "semantic-tool-"));
    setDurableStoresForTests(
      new JsonlRunStore(dir),
      new JsonlConversationStore(dir),
    );
  });

  afterEach(() => {
    setAgentRunnerForTests(null);
    setDurableStoresForTests(
      new JsonlRunStore(mkdtempSync(path.join(tmpdir(), "teardown-"))),
      new JsonlConversationStore(mkdtempSync(path.join(tmpdir(), "teardown-"))),
    );
    resetAgentRunsForTests();
    resetAgentSessionsForTests();
    rmSync(dir, { recursive: true, force: true });
  });

  it("returns 400 TECHNICAL_OVERRIDE_REJECTED without starting a run", async () => {
    let started = false;
    setAgentRunnerForTests(async () => {
      started = true;
      return { status: "success", responseText: "ok" } as WorkbenchOutcome;
    });
    const response = await POST(new Request("http://localhost/api/semantic-tools", {
      method: "POST",
      body: JSON.stringify({
        contractVersion: 1,
        tool: "diagnose_material_supply",
        utterance: "A100 库存",
        rfcName: "BAPI_X",
      }),
    }));
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({
      errorType: "TECHNICAL_OVERRIDE_REJECTED",
    });
    expect(started).toBe(false);
  });

  it("returns 404 for an unknown tool", async () => {
    const response = await POST(new Request("http://localhost/api/semantic-tools", {
      method: "POST",
      body: JSON.stringify({
        contractVersion: 1,
        tool: "MM.Inventory.GetAvailability",
        utterance: "库存",
      }),
    }));
    expect(response.status).toBe(404);
  });

  it("runs the governed pipeline and maps the settled outcome", async () => {
    setAgentRunnerForTests(async () =>
      ({ status: "clarification", responseText: "请提供工厂" } as WorkbenchOutcome));
    const response = await POST(new Request("http://localhost/api/semantic-tools", {
      method: "POST",
      body: JSON.stringify({
        contractVersion: 1,
        tool: "diagnose_material_supply",
        utterance: "A100 够不够用",
        slots: { material: "A100" },
      }),
    }));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({
      contractVersion: 1,
      tool: "diagnose_material_supply",
      status: "clarification",
      narrative: { summary: "请提供工厂" },
    });
    expect(body.runId).toMatch(/^run-/);
    expect(body.capabilityChain).toEqual([]);
  });

  it("returns 400 for malformed JSON", async () => {
    const response = await POST(new Request("http://localhost/api/semantic-tools", {
      method: "POST",
      body: "{not json",
    }));
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ errorType: "INVALID_REQUEST" });
  });
});
