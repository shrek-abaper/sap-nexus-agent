import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { existsSync } from "node:fs";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { POST } from "../../../app/api/semantic-tools/route";
import {
  resetAgentRunsForTests,
  resetAgentSessionsForTests,
  setAgentRunnerForTests,
  setDurableStoresForTests,
} from "../agent-runtime-adapter";
import { JsonlRunStore } from "../durable/jsonl-run-store";
import { JsonlConversationStore } from "../durable/jsonl-conversation-store";
import { tmpdir } from "node:os";
import casesFile from "./__fixtures__/cross-harness-cases.json";

// Cross-harness gate: identical recorded Gateway responses drive
//  (a) the Python CLI directly (existing harness) and
//  (b) the semantic-tool facade over the real spawned-Python runner (dsh path)
// Business values (capability chain, fact material/plant/value/unit) must match.
// Fully offline: the only SAP surface is the in-test fixture HTTP server.

const here = path.dirname(fileURLToPath(import.meta.url));
// semantic-tools -> runtime -> src -> frontend -> repo root
const repoRoot = path.resolve(here, "..", "..", "..", "..");
const venvPython = path.join(repoRoot, ".venv", "bin", "python");

type CrossCase = {
  id: string;
  tool: string;
  slots: Record<string, unknown>;
  query: string;
  capabilityId: string;
  execute: Record<string, unknown>;
  expectedFacts: Array<{ material?: string; plant?: string; value: string; unit: string }>;
};

const cases = (casesFile as { cases: CrossCase[] }).cases;

type NormalizedFact = { key: string; value: string; unit: string };

function runPythonCli(query: string, url: string): Promise<{ status: number; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(venvPython, [
      "-m", "sap_nexus_agent.cli",
      query,
      "--json",
      "--gateway-url", url,
    ], { cwd: repoRoot });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error("Python CLI timed out"));
    }, 60_000);
    child.stdout.on("data", (chunk) => { stdout += String(chunk); });
    child.stderr.on("data", (chunk) => { stderr += String(chunk); });
    child.on("error", reject);
    child.on("close", (status) => {
      clearTimeout(timer);
      resolve({ status: status ?? -1, stdout, stderr });
    });
  });
}

function normalizeFact(raw: Record<string, unknown>): NormalizedFact {
  // Scalar facts use numeric value; SD/FI/PO LIST facts carry values in evidence.
  const evidence = Array.isArray(raw.evidence) ? raw.evidence[0] as Record<string, unknown> : undefined;
  const value = raw.value ?? evidence?.orderQuantity ?? evidence?.netValue ?? evidence?.amtDoccur ?? "";
  const unit = String(raw.unit ?? "");
  const party = String(raw.material ?? evidence?.soldTo ?? evidence?.supplier ?? "");
  const plant = String(raw.plant ?? "");
  return { key: `${party}|${plant}|${String(value)}|${unit}`, value: String(value), unit };
}

function factKey(fact: NormalizedFact): string {
  return fact.key;
}

describe.skipIf(!existsSync(venvPython))("cross-harness consistency (offline fixtures)", () => {
  let server: Server;
  let gatewayUrl: string;
  let currentCase: CrossCase;
  let storeDir: string;
  let previousGatewayUrl: string | undefined;

  beforeAll(async () => {
    server = createServer((req, res) => {
      // Always drain the request body before responding, or keep-alive
      // clients can stall on the half-read request.
      let raw = "";
      req.on("data", (chunk) => { raw += chunk; });
      req.on("end", () => {
        void raw;
        const url = new URL(req.url ?? "/", "http://fixture");
        const match = url.pathname.match(/^\/capabilities\/[^/]+\/(validate|execute)$/);
        if (!match) {
          res.writeHead(404).end();
          return;
        }
        const payload = match[1] === "validate"
          ? {
              traceId: `${currentCase.id}-validate`,
              capabilityId: currentCase.capabilityId,
              success: true,
              errorType: "NONE",
              messages: [],
            }
          : currentCase.execute;
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify(payload));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    gatewayUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    previousGatewayUrl = process.env.SAP_NEXUS_GATEWAY_URL;
    process.env.SAP_NEXUS_GATEWAY_URL = gatewayUrl;

    storeDir = mkdtempSync(path.join(tmpdir(), "cross-harness-"));
    setDurableStoresForTests(
      new JsonlRunStore(storeDir),
      new JsonlConversationStore(storeDir),
    );
  }, 30_000);

  afterAll(async () => {
    setAgentRunnerForTests(null);
    resetAgentRunsForTests();
    resetAgentSessionsForTests();
    if (previousGatewayUrl === undefined) delete process.env.SAP_NEXUS_GATEWAY_URL;
    else process.env.SAP_NEXUS_GATEWAY_URL = previousGatewayUrl;
    await server.close();
    rmSync(storeDir, { recursive: true, force: true });
  });

  it.each(cases)("$id: dsh facade path matches the Python CLI on identical fixtures", async (testCase) => {
    currentCase = testCase;

    // (a) Python CLI reference path. Async spawn (spawnSync would freeze the
    // event loop and deadlock the in-process fixture HTTP server).
    const cli = await runPythonCli(testCase.query, gatewayUrl);
    if (cli.status !== 0 || !cli.stdout.trim()) {
      throw new Error(`CLI failed status=${cli.status} stdout=${JSON.stringify(cli.stdout.slice(0, 200))} stderr=${cli.stderr.slice(-1500)}`);
    }
    const reference = JSON.parse(cli.stdout) as {
      status: string;
      callPlan?: { capabilityId?: string } | null;
      fact?: Record<string, unknown> | null;
      facts?: Array<Record<string, unknown>> | null;
    };
    expect(reference.status).toBe("success");
    expect(reference.callPlan?.capabilityId).toBe(testCase.capabilityId);
    const referenceFacts = [reference.fact, ...(reference.facts ?? [])]
      .filter((fact): fact is Record<string, unknown> => Boolean(fact))
      .map(normalizeFact);

    // (b) dsh harness path: semantic-tool request through the real runner
    // (the adapter spawns the same Python CLI against the same fixture gateway).
    const response = await POST(new Request("http://localhost/api/semantic-tools", {
      method: "POST",
      body: JSON.stringify({
        contractVersion: 2,
        tool: testCase.tool,
        utterance: testCase.query,
        slots: testCase.slots,
      }),
    }));
    expect(response.status).toBe(200);
    const harness = await response.json() as {
      status: string;
      capabilityChain: Array<{ capabilityId: string }>;
      facts: Array<Record<string, unknown>>;
    };
    expect(harness.status).toBe("complete");
    expect(harness.capabilityChain.map((entry) => entry.capabilityId))
      .toContain(testCase.capabilityId);
    const harnessFacts = harness.facts.map(normalizeFact);

    // Business-value equality, order-independent (list facts are per-record).
    const byKey = (facts: NormalizedFact[]) => new Map(facts.map((fact) => [factKey(fact), fact]));
    const referenceMap = byKey(referenceFacts);
    const harnessMap = byKey(harnessFacts);
    expect([...harnessMap.keys()].sort()).toEqual([...referenceMap.keys()].sort());
    for (const [key, expected] of referenceMap) {
      expect(harnessMap.get(key), key).toBeDefined();
      expect(harnessMap.get(key)?.value).toBe(expected.value);
      expect(harnessMap.get(key)?.unit).toBe(expected.unit);
    }
    for (const expected of testCase.expectedFacts) {
      const match = [...harnessMap.values()].find((fact) =>
        fact.value === expected.value && fact.unit === expected.unit);
      expect(match, `${expected.value} ${expected.unit}`).toBeDefined();
    }
  }, 120_000);
});
