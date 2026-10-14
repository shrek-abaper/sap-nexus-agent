/**
 * Controlled subprocess adapter for the Python analysis runtime.
 *
 * The child performs normalization and operator execution only; it never
 * gets credentials, a gateway URL, or a principal. Values travel via stdin
 * JSON (never argv), and stdout must satisfy the wire output shape.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

import type { AnalysisWireInput, AnalysisWireOutput, AnalysisStatus } from "./types";

export interface AdapterOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  env?: NodeJS.ProcessEnv;
}

export class AnalysisAdapterError extends Error {
  constructor(
    message: string,
    public readonly causeDetail?: string,
  ) {
    super(message);
    this.name = "AnalysisAdapterError";
  }
}

const STATUSES = new Set<AnalysisStatus>([
  "complete",
  "partial",
  "clarification",
  "capability_gap",
  "semantic_gap",
  "rejected",
  "failed",
]);

function repoRootPath(): string {
  if (process.env.SAP_NEXUS_AGENT_ROOT) {
    return process.env.SAP_NEXUS_AGENT_ROOT;
  }
  const cwd = process.cwd();
  return path.basename(cwd) === "frontend" ? path.dirname(cwd) : cwd;
}

function pythonExecutable(repoRoot: string): string {
  if (process.env.SAP_NEXUS_AGENT_PYTHON) {
    return process.env.SAP_NEXUS_AGENT_PYTHON;
  }
  const venvPython = path.join(repoRoot, ".venv", "bin", "python");
  return existsSync(venvPython) ? venvPython : "python3";
}

/** Remove gateway/credential/principal values inherited from the parent. */
export function sanitizeChildEnvironment(
  env: NodeJS.ProcessEnv,
  pythonPath: string,
): NodeJS.ProcessEnv {
  const sanitized: Record<string, string | undefined> = {};
  for (const [key, value] of Object.entries(env)) {
    if (key === "SAP_NEXUS_APPROVAL_TOKEN") continue;
    if (key === "SAP_NEXUS_GATEWAY_URL") continue;
    if (key === "SAP_NEXUS_PRINCIPAL") continue;
    sanitized[key] = value;
  }
  sanitized.PYTHONPATH = [pythonPath, env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  return sanitized as NodeJS.ProcessEnv;
}

function validateOutput(value: unknown): AnalysisWireOutput {
  if (typeof value !== "object" || value === null) {
    throw new AnalysisAdapterError("analysis output is not an object");
  }
  const output = value as Partial<AnalysisWireOutput>;
  if (output.wireVersion !== 1) {
    throw new AnalysisAdapterError("analysis output wireVersion mismatch");
  }
  if (typeof output.status !== "string" || !STATUSES.has(output.status)) {
    throw new AnalysisAdapterError("analysis output status invalid");
  }
  if (!Array.isArray(output.facts) || !Array.isArray(output.results)) {
    throw new AnalysisAdapterError("analysis output missing facts/results arrays");
  }
  return output as AnalysisWireOutput;
}

export async function runPythonAnalysis(
  input: AnalysisWireInput,
  options: AdapterOptions = {},
): Promise<AnalysisWireOutput> {
  const repoRoot = repoRootPath();
  const timeoutMs = options.timeoutMs ?? 90_000;
  const payload = JSON.stringify(input);
  const maxBytes = 2 * 1024 * 1024;
  if (Buffer.byteLength(payload, "utf8") > maxBytes) {
    throw new AnalysisAdapterError("analysis input exceeds size bound");
  }

  const agentPath = path.join(repoRoot, "agent");
  const env = sanitizeChildEnvironment(options.env ?? process.env, agentPath);
  const args = ["-m", "sap_nexus_agent.ontology_planning.analysis_runtime"];

  return new Promise<AnalysisWireOutput>((resolve, reject) => {
    let settled = false;
    const child = spawn(pythonExecutable(repoRoot), args, {
      cwd: repoRoot,
      env,
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      fail(new AnalysisAdapterError("analysis subprocess timed out"));
    }, timeoutMs);

    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    };

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => fail(new AnalysisAdapterError("subprocess could not start", error.message)));
    child.on("close", (code) => {
      if (settled) return;
      clearTimeout(timer);
      if (code !== 0) {
        fail(new AnalysisAdapterError("analysis subprocess failed", stderr.slice(-500)));
        return;
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(stdout.trim());
      } catch {
        fail(new AnalysisAdapterError("analysis output is not valid JSON"));
        return;
      }
      try {
        resolve(validateOutput(parsed));
      } catch (error) {
        fail(error as AnalysisAdapterError);
      }
      settled = true;
    });

    options.signal?.addEventListener(
      "abort",
      () => {
        child.kill();
        fail(new AnalysisAdapterError("analysis subprocess aborted"));
      },
      { once: true },
    );
    child.stdin.end(payload);
  });
}
