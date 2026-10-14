/**
 * DynamicReadCoordinator — TS orchestration for ontology-governed analysis.
 *
 * Planning and analysis live in Python (single semantic/arithmetic authority).
 * This class executes the read half through the existing PlanExecutor against
 * the existing GatewayClient (FakeGateway in offline tests), then invokes the
 * controlled Python analysis subprocess once. It must never import
 * composition/recommendation/projection/semantic-tools modules.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

import type { DurableRunStore } from "../durable/types";
import { PlanExecutor } from "../plan-executor/plan-executor";
import type {
  GatewayClient,
  NodeFactRecord,
  PlanGraphV2,
} from "../plan-executor/types";
import { runPythonAnalysis } from "./python-analysis-adapter";
import type { AnalysisWireInput, AnalysisWireOutput } from "./types";

export interface PlanEnvelope {
  status: string;
  plan: {
    planId: string;
    readPlan: PlanGraphV2;
    analysisPlan: AnalysisWireInput["analysisPlan"];
    semanticSnapshotId?: string;
    registrySnapshotId?: string;
    limits?: Record<string, unknown>;
  };
  releaseIds: {
    semanticSnapshotId: string;
    registrySnapshotId: string;
  };
  reasons?: string[];
}

export interface AnalysisEnvelope extends AnalysisWireOutput {
  planId: string;
  writeGatewayCalls: number;
  failedNodeIds: string[];
}

export class DynamicAnalysisError extends Error {}

function repoRootPath(): string {
  if (process.env.SAP_NEXUS_AGENT_ROOT) return process.env.SAP_NEXUS_AGENT_ROOT;
  const cwd = process.cwd();
  return path.basename(cwd) === "frontend" ? path.dirname(cwd) : cwd;
}

function pythonExecutable(repoRoot: string): string {
  if (process.env.SAP_NEXUS_AGENT_PYTHON) return process.env.SAP_NEXUS_AGENT_PYTHON;
  const venv = path.join(repoRoot, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

export type AnalysisRunner = (
  input: AnalysisWireInput,
) => Promise<AnalysisWireOutput> | AnalysisWireOutput;

/** Default analysis runner: one controlled Python subprocess via the adapter. */
export function subprocessAnalysisRunner(opts: { timeoutMs?: number } = {}): AnalysisRunner {
  return (input: AnalysisWireInput) => runPythonAnalysis(input, opts);
}

/** Planner runner: one controlled Python subprocess returning the plan envelope. */
export function subprocessPlannerRunner(opts: { timeoutMs?: number } = {}): (
  request: unknown,
) => Promise<PlanEnvelope> {
  return async (request: unknown): Promise<PlanEnvelope> => {
    const repoRoot = repoRootPath();
    const env: Record<string, string | undefined> = {};
    for (const [key, value] of Object.entries(process.env)) {
      if (key === "SAP_NEXUS_APPROVAL_TOKEN") continue;
      if (key === "SAP_NEXUS_GATEWAY_URL") continue;
      if (key === "SAP_NEXUS_PRINCIPAL") continue;
      env[key] = value;
    }
    env.PYTHONPATH = [path.join(repoRoot, "agent"), process.env.PYTHONPATH]
      .filter(Boolean)
      .join(path.delimiter);

    return new Promise<PlanEnvelope>((resolvePromise, rejectPromise) => {
      let settled = false;
      let stdout = "";
      let stderr = "";
      const child = spawn(
        pythonExecutable(repoRoot),
        ["-m", "sap_nexus_agent.ontology_planning.analysis_runtime", "--mode", "plan"],
        { cwd: repoRoot, env: env as NodeJS.ProcessEnv },
      );
      const timer = setTimeout(
        () => {
          child.kill();
          fail(new DynamicAnalysisError("planner subprocess timed out"));
        },
        opts.timeoutMs ?? 90_000,
      );
      const fail = (error: Error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        rejectPromise(error);
      };
      child.stdout.on("data", (chunk: Buffer) => {
        stdout += chunk.toString("utf8");
      });
      child.stderr.on("data", (chunk: Buffer) => {
        stderr += chunk.toString("utf8");
      });
      child.on("error", (error) => fail(new DynamicAnalysisError(error.message)));
      child.on("close", (code) => {
        if (settled) return;
        clearTimeout(timer);
        if (code !== 0) {
          fail(new DynamicAnalysisError(`planner subprocess exit ${code}: ${stderr.slice(-300)}`));
          return;
        }
        try {
          resolvePromise(JSON.parse(stdout.trim()) as PlanEnvelope);
          settled = true;
        } catch {
          fail(new DynamicAnalysisError("planner output is not valid JSON"));
        }
      });
      child.stdin.end(JSON.stringify(request));
    });
  };
}

export interface DynamicReadCoordinatorDeps {
  store: DurableRunStore;
  gateway: GatewayClient;
  workerId: string;
  planRequest: unknown;
  runAnalysis?: AnalysisRunner;
  planRunner?: (request: unknown) => Promise<PlanEnvelope>;
}

export class DynamicReadCoordinator {
  constructor(private readonly deps: DynamicReadCoordinatorDeps) {}

  async execute(): Promise<AnalysisEnvelope> {
    const planRunner = this.deps.planRunner ?? subprocessPlannerRunner();
    const envelope = await planRunner(this.deps.planRequest);
    if (envelope.status !== "planned") {
      throw new DynamicAnalysisError(
        `planning did not complete: ${envelope.status} ${(envelope.reasons ?? []).join("; ")}`,
      );
    }
    const readPlan = envelope.plan.readPlan;
    if (readPlan.actionPartition.length !== 0 || readPlan.executionMode !== "READ_ONLY") {
      throw new DynamicAnalysisError("WRITE_REJECTED: plan is not READ_ONLY");
    }
    for (const node of readPlan.nodes) {
      if (node.governance.requiresApproval) {
        throw new DynamicAnalysisError(`WRITE_REJECTED: approval-bearing node ${node.nodeId}`);
      }
    }

    const runId = `dyn-${envelope.plan.planId.slice(-12)}`;
    const executor = new PlanExecutor(this.deps.store, this.deps.gateway, this.deps.workerId);
    const execution = await executor.execute(readPlan, runId, readPlan.snapshotId);

    const nodeResults = execution.succeededNodeResults.map(
      (record: NodeFactRecord) => ({
        nodeId: record.nodeId,
        capabilityId: record.capabilityId,
        parameters: record.parameters,
        gatewayTraceId: record.gatewayTraceId,
        executedAt: record.nodeExecutedAt,
        data: record.executeData,
      }),
    );

    const wire: AnalysisWireInput = {
      wireVersion: 1,
      runId,
      release: envelope.releaseIds,
      nodeResults,
      analysisPlan: envelope.plan.analysisPlan,
      requestedConclusions: [],
    };
    const runAnalysis = this.deps.runAnalysis ?? subprocessAnalysisRunner();
    const analysis = await Promise.resolve(runAnalysis(wire));

    return {
      ...analysis,
      planId: envelope.plan.planId,
      writeGatewayCalls: this.gatewayWriteCalls(),
      failedNodeIds: execution.failed,
    };
  }

  private gatewayWriteCalls(): number {
    const gateway = this.deps.gateway as unknown as {
      executeCalls?: Array<{ capabilityId: string }>;
    };
    const writeIds = new Set(["MM.PR.CreateDraft"]);
    if (!gateway.executeCalls) return 0;
    return gateway.executeCalls.filter((call) => writeIds.has(call.capabilityId)).length;
  }
}
