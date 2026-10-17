/**
 * Server-only handler for the flag-gated analyze_business_question DSH tool.
 * Invokes the C2 Python analysis runtime over stdin (offline fake
 * interpreter + fake gateway) and maps its envelope to a discriminated
 * OntologyAnalysisToolResponse with a deterministic Chinese narrative.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

export const ONTOLOGY_ANALYSIS_TOOL = "analyze_business_question";

export type OntologyAnalysisStatus =
  | "complete"
  | "partial"
  | "clarification"
  | "capability_gap"
  | "semantic_gap"
  | "rejected"
  | "failed";

export type QuestionType =
  | "stock-with-unit"
  | "po-grouped-by-supplier"
  | "po-by-vendor"
  | "arrivals-next-week"
  | "stockout-certainty"
  | "create-pr";

export const QUESTION_CASES: Record<QuestionType, string> = {
  "stock-with-unit": "q1-stock-and-unit",
  "po-grouped-by-supplier": "q2-po-group-by-supplier",
  "po-by-vendor": "q3-supplier-filter",
  "arrivals-next-week": "q5-arrivals-next-week",
  "stockout-certainty": "q6-stockout-certainty",
  "create-pr": "write-create-pr",
};

export interface OntologyFact {
  factTypeRef: string;
  fields: Record<string, { value: string; semanticType: string }>;
  unit: { field: string; value: string } | null;
}

export interface OntologyResultRow {
  groupKey?: Record<string, unknown>;
  measures?: Record<string, { decimal: string; unit: string }>;
  [key: string]: unknown;
}

export interface OntologyResult {
  nodeId: string;
  operatorId: string;
  status: OntologyAnalysisStatus;
  rows: OntologyResultRow[];
  excludedRows?: { factId: string; reason: string }[];
}

export interface OntologyAnalysisToolResponse {
  kind: "ontology-analysis";
  contractVersion: 1;
  tool: typeof ONTOLOGY_ANALYSIS_TOOL;
  status: OntologyAnalysisStatus;
  runId: string;
  facts: OntologyFact[];
  results: OntologyResult[];
  gaps: string[];
  limitations: string[];
  writeGatewayCalls?: number;
  narrative: { summary: string; limitations: string[] };
  error?: { errorType: string; message: string };
}

/** C2 coordinator EvidenceResponse subset consumed here. facts/reasons are
 * optional: early-exit envelopes (e.g. clarification) omit them entirely. */
export interface OntologyEvidence {
  schemaVersion: 1;
  status: OntologyAnalysisStatus;
  plan?: { planId?: string };
  facts?: OntologyFact[];
  analysis?: {
    results: OntologyResult[];
    uncoveredConclusions?: { conclusionId: string; reason: string }[];
    conflicts?: string[];
  };
  reasons?: string[];
  nodeFailures?: string[];
  writeGatewayCalls: number;
  notRun: string[];
}

export type OntologyAnalysisRunner = (request: {
  caseId?: string;
  interpreter?: "fake" | "model";
  utterance?: string;
  slots: Record<string, string>;
  scope: Record<string, string>;
}) => Promise<OntologyEvidence>;

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

/** Default runner: one credential-free Python subprocess. */
export function subprocessOntologyRunner(timeoutMs = 90_000): OntologyAnalysisRunner {
  return (request) =>
    new Promise<OntologyEvidence>((resolvePromise, rejectPromise) => {
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

      let settled = false;
      let stdout = "";
      let stderr = "";
      const child = spawn(
        pythonExecutable(repoRoot),
        ["-m", "sap_nexus_agent.ontology_planning.analysis_runtime", "--mode", "analyze"],
        { cwd: repoRoot, env: env as NodeJS.ProcessEnv },
      );
      const timer = setTimeout(
        () => {
          child.kill();
          fail(new Error("ontology analysis subprocess timed out"));
        },
        timeoutMs,
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
      child.on("error", (error) => fail(error));
      child.on("close", (code) => {
        if (settled) return;
        clearTimeout(timer);
        if (code === 0 || code === 3) {
          try {
            settled = true;
            resolvePromise(JSON.parse(stdout.trim()) as OntologyEvidence);
          } catch {
            fail(new Error("ontology analysis output is not valid JSON"));
          }
          return;
        }
        fail(new Error(`ontology analysis exit ${code}: ${stderr.slice(-300)}`));
      });
      child.stdin.end(
        JSON.stringify({
          schemaVersion: 1,
          ...(request.caseId ? { caseId: request.caseId } : {}),
          interpreter: request.interpreter ?? "fake",
          ...(request.utterance ? { utterance: request.utterance } : {}),
          slots: request.slots,
          scope: request.scope,
        }),
      );
    });
}

const STATUS_HEADERS: Record<OntologyAnalysisStatus, string> = {
  complete: "本体约束只读分析完成",
  partial: "本体约束只读分析完成（部分）",
  clarification: "需要澄清后才能分析",
  capability_gap: "能力缺口：当前注册能力无法回答",
  semantic_gap: "语义缺口：所需事实字段不存在",
  rejected: "已拒绝：本体分析路径不执行写入",
  failed: "分析失败",
};

function factLine(fact: OntologyFact): string {
  const values = Object.entries(fact.fields)
    .map(([name, field]) => `${name}=${field.value}${fact.unit && fact.unit.field === name ? " " + fact.unit.value : ""}`)
    .join("，");
  return `- ${fact.factTypeRef}：${values}`;
}

function resultLine(result: OntologyResult): string {
  const rows = result.rows
    .map((row) => {
      const key = row.groupKey ? Object.values(row.groupKey).join("/") : "";
      const measures = row.measures
        ? Object.values(row.measures).map((measure) => `${measure.decimal} ${measure.unit}`).join("，")
        : "";
      return [key, measures].filter(Boolean).join("：");
    })
    .join("；");
  return `- ${result.operatorId}（${result.status}）：${rows || "（无输出行）"}`;
}

function buildNarrative(
  status: OntologyAnalysisStatus,
  facts: OntologyFact[],
  results: OntologyResult[],
  reasons: string[],
  uncovered: string[],
): string {
  const lines: string[] = [STATUS_HEADERS[status] ?? "分析结束", ""];
  if (facts.length > 0) {
    lines.push("事实：");
    lines.push(...facts.map(factLine));
    lines.push("");
  }
  if (results.length > 0) {
    lines.push("分析：");
    lines.push(...results.map(resultLine));
    lines.push("");
  }
  const gapReasons = [...reasons, ...uncovered];
  if (gapReasons.length > 0) {
    lines.push("缺口/限制：");
    lines.push(...gapReasons.map((reason) => `- ${reason}`));
    lines.push("");
  }
  lines.push("（离线样例数据，未连接 SAP；采购订单量不是到货量，库存快照不等于 ATP）");
  return lines.join("\n");
}

function toToolResponse(
  questionType: QuestionType | "model",
  evidence: OntologyEvidence,
): OntologyAnalysisToolResponse {
  // Early-exit envelopes (clarification etc.) omit facts/reasons entirely;
  // normalize before mapping instead of trusting the declared shape.
  const facts = evidence.facts ?? [];
  const reasons = evidence.reasons ?? [];
  const results = evidence.analysis?.results ?? [];
  const uncovered = (evidence.analysis?.uncoveredConclusions ?? []).map((item) => item.reason);
  const exclusions = results.flatMap((result) =>
    (result.excludedRows ?? []).map((row) => row.reason),
  );
  const conflicts = evidence.analysis?.conflicts ?? [];
  const failures = evidence.nodeFailures ?? [];
  const limitations = [...new Set([...exclusions, ...conflicts, ...failures])];
  const summary = buildNarrative(
    evidence.status,
    facts,
    results,
    reasons,
    uncovered,
  );
  const response: OntologyAnalysisToolResponse = {
    kind: "ontology-analysis",
    contractVersion: 1,
    tool: ONTOLOGY_ANALYSIS_TOOL,
    status: evidence.status,
    runId: evidence.plan?.planId ?? `ont-${questionType}`,
    facts,
    results,
    gaps: [...reasons, ...uncovered],
    limitations,
    writeGatewayCalls: evidence.writeGatewayCalls,
    narrative: { summary, limitations },
  };
  if (evidence.status === "failed") {
    response.error = {
      errorType: "ANALYSIS_FAILED",
      message: reasons.join("; ") || "unknown",
    };
  }
  return response;
}

function liveModelEnabled(): boolean {
  return process.env.SAP_NEXUS_LLM_LIVE === "1";
}

export function createOntologyAnalysisHandler(
  runner: OntologyAnalysisRunner = subprocessOntologyRunner(),
) {
  return async (args: Record<string, unknown>): Promise<OntologyAnalysisToolResponse> => {
    const question = typeof args.question === "string" ? args.question : "";
    const slots: Record<string, string> = {};
    for (const key of ["material", "plant", "vendor"]) {
      const value = args[key];
      if (typeof value === "string" && value) slots[key] = value;
    }
    const scope: Record<string, string> = {};
    if (slots.plant) scope.plant = slots.plant;

    if (question && liveModelEnabled()) {
      const evidence = await runner({
        interpreter: "model",
        utterance: question,
        slots,
        scope,
      });
      return toToolResponse("model", evidence);
    }

    const questionType = String(args.questionType ?? "") as QuestionType;
    const caseId = QUESTION_CASES[questionType];
    if (!caseId) {
      return {
        kind: "ontology-analysis",
        contractVersion: 1,
        tool: ONTOLOGY_ANALYSIS_TOOL,
        status: "rejected",
        runId: "ont-invalid",
        facts: [],
        results: [],
        gaps: [],
        limitations: [],
        narrative: {
          summary: "已拒绝：未知的问题类型；只能从注册的 questionType 枚举中选择。",
          limitations: [],
        },
        error: { errorType: "INVALID_QUESTION_TYPE", message: String(args.questionType ?? "") },
      };
    }
    const evidence = await runner({ caseId, slots, scope });
    return toToolResponse(questionType, evidence);
  };
}
