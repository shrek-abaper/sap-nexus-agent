import type { AgentRunEvent, AgentRunSnapshot } from "@/runtime/run-event-schema";
import type { JsonValue, RedactedArtifact } from "@/shared/types/artifacts";
import type { ChatTurn, Session } from "./chat-types";

export type WorkbenchResultTone = "idle" | "success" | "clarification" | "failure" | "running";

export type WorkbenchResult = {
  title: string;
  body: string;
  tone: WorkbenchResultTone;
  meta: string;
};

export type ReasoningStep = {
  sequence: number;
  label: string;
  state: AgentRunEvent["state"];
  status: "done" | "current" | "failed";
};

export type DetailGroup = {
  title: string;
  summary: string;
  artifacts: RedactedArtifact[];
};

export type MatchDecisionCandidate = {
  capabilityId: string;
  parameters: Record<string, string>;
  missing: string[];
};

export type MatchDecisionHandoff = {
  reason: string;
  matchedIntents: MatchDecisionCandidate[];
  utterance: string;
  registrySnapshotId: string;
};

export type MatchDecisionView = {
  decisionType: "SELECT" | "CLARIFY" | "REJECT" | "SHOW_OPTIONS" | "ESCALATE_TO_PLANNER";
  candidates?: MatchDecisionCandidate[];
  handoff?: MatchDecisionHandoff;
  rationale: string;
};

// ---- S2-B dry-run preview (Task 9) ----

export type DryRunParameterBinding = {
  parameterName: string;
  source: { kind: string; constraintName?: string };
};

export type DryRunPlanNode = {
  nodeId: string;
  capabilityId: string;
  parameterBindings: DryRunParameterBinding[];
  producesFactTypes: string[];
};

export type DryRunGoalOutput = {
  factTypeId: string;
  producerNodeId: string;
};

export type DryRunPlanGraph = {
  planId: string;
  goalId: string;
  executionMode: string;
  snapshotId?: string;
  nodes: DryRunPlanNode[];
  edges: unknown[];
  topologicalOrder: string[];
  goalOutputs: DryRunGoalOutput[];
};

export type DryRunGap = {
  kind: string;
  detail: string;
};

export type DryRunFlag = {
  kind: string;
  detail: string;
};

export type DryRunView = {
  planGraph: DryRunPlanGraph;
  gaps: DryRunGap[];
  governanceFlags: DryRunFlag[];
  rationale: string;
};

export type WorkbenchViewModel = {
  result: WorkbenchResult;
  reasoningSteps: ReasoningStep[];
  detailGroups: DetailGroup[];
  artifacts: {
    intent?: RedactedArtifact;
    capability?: RedactedArtifact;
    callPlan?: RedactedArtifact;
    validation?: RedactedArtifact;
    executionResult?: RedactedArtifact;
    reasoningFact?: RedactedArtifact;
    narrative?: RedactedArtifact;
    trace?: RedactedArtifact;
    matchDecision?: RedactedArtifact;
    agentTraceId?: string;
    gatewayTraceId?: string;
  };
};

const eventLabels: Record<AgentRunEvent["type"], string> = {
  run_started: "启动 Agent Run",
  intent_parsed: "解析业务意图",
  capability_selected: "选择注册能力",
  callplan_created: "创建 CallPlan",
  approval_state_changed: "检查 Human Approval",
  gateway_validate_started: "开始 Gateway 校验",
  gateway_validate_completed: "Gateway 校验完成",
  gateway_execute_started: "开始 Gateway 执行",
  gateway_execute_completed: "Gateway 执行完成",
  reasoning_fact_created: "生成 ReasoningFact",
  narrative_created: "生成中文结论",
  trace_linked: "绑定 Trace",
  run_completed: "完成运行",
  run_failed: "运行失败",
  match_decision_created: "匹配决策"
};

export function buildWorkbenchViewModel(snapshot: AgentRunSnapshot | null): WorkbenchViewModel {
  const events = snapshot?.events ?? [];
  const artifacts = collectArtifacts(events);
  const result = buildResult(snapshot, artifacts);
  const reasoningEvents = events.filter((event) => event.type !== "run_started" && event.type !== "run_completed");
  const reasoningSteps: ReasoningStep[] = reasoningEvents.map((event, index) => ({
      sequence: index + 1,
      label: eventLabels[event.type],
      state: event.state,
      status: stepStatus(event, index, reasoningEvents.length)
    }));

  return {
    result,
    reasoningSteps,
    detailGroups: buildDetailGroups(artifacts),
    artifacts
  };
}

function stepStatus(event: AgentRunEvent, index: number, eventCount: number): ReasoningStep["status"] {
  if (event.type === "run_failed") {
    return "failed";
  }
  return index === eventCount - 1 ? "current" : "done";
}

function collectArtifacts(events: AgentRunEvent[]): WorkbenchViewModel["artifacts"] {
  const artifactByKind = (kind: RedactedArtifact["kind"]) =>
    events.find((event) => event.artifact?.kind === kind)?.artifact;
  return {
    intent: artifactByKind("intent"),
    capability: artifactByKind("capability"),
    callPlan: artifactByKind("callplan"),
    validation: artifactByKind("validation"),
    executionResult: artifactByKind("execution-result"),
    reasoningFact: artifactByKind("reasoning-fact"),
    narrative: artifactByKind("narrative"),
    trace: artifactByKind("trace"),
    matchDecision: artifactByKind("match-decision"),
    agentTraceId: events.find((event) => event.agentTraceId)?.agentTraceId,
    gatewayTraceId: events.find((event) => event.gatewayTraceId)?.gatewayTraceId
  };
}

function buildResult(
  snapshot: AgentRunSnapshot | null,
  artifacts: WorkbenchViewModel["artifacts"]
): WorkbenchResult {
  if (!snapshot) {
    return {
      title: "先提出一个 SAP 业务问题",
      body: "输入库存、能力或执行证据相关问题后，Workbench 会先展示结论，再展开 Harness 过程。",
      tone: "idle",
      meta: "Waiting for query"
    };
  }
  if (snapshot.error) {
    return {
      title: snapshot.error.errorType,
      body: snapshot.error.message,
      tone: "failure",
      meta: `Failed at ${snapshot.error.stage}`
    };
  }
  const narrative = textFromNarrative(artifacts.narrative);
  if (narrative) {
    return {
      title: "库存查询结果",
      body: narrative,
      tone: "success",
      meta: artifacts.executionResult ? "ExecutionResult -> ReasoningFact -> Narrative" : "Clarification"
    };
  }
  return {
    title: "Agent 正在推理",
    body: "已收到问题，正在解析意图、选择能力并收集执行证据。",
    tone: "running",
    meta: snapshot.state
  };
}

function textFromNarrative(artifact?: RedactedArtifact): string | null {
  const payload = artifact?.payload;
  if (payload && typeof payload === "object" && !Array.isArray(payload) && typeof payload.text === "string") {
    return payload.text;
  }
  return null;
}

function buildDetailGroups(artifacts: WorkbenchViewModel["artifacts"]): DetailGroup[] {
  const rawArtifacts = [
    artifacts.intent,
    artifacts.capability,
    artifacts.callPlan,
    artifacts.validation,
    artifacts.executionResult,
    artifacts.reasoningFact,
    artifacts.narrative,
    artifacts.trace
  ].filter((artifact): artifact is RedactedArtifact => Boolean(artifact));

  return [
    group("意图与能力选择", "自然语言理解、参数抽取、注册能力闭集选择。", [
      artifacts.intent,
      artifacts.capability
    ]),
    group("执行计划", "CallPlan 与人审状态，READ 路径默认不需要审批。", [artifacts.callPlan]),
    group("Gateway 执行证据", "Gateway validate / execute 的结构化结果。", [
      artifacts.validation,
      artifacts.executionResult
    ]),
    group("事实化与叙事", "ExecutionResult 转成 ReasoningFact 后再生成中文结论。", [
      artifacts.reasoningFact,
      artifacts.narrative
    ]),
    group("Trace / Audit", "Agent trace 与 Gateway trace 的审计入口。", [artifacts.trace]),
    group("原始产物", "保留当前页面已有的全部 artifact JSON，便于回放与排障。", rawArtifacts)
  ];
}

function group(title: string, summary: string, artifacts: Array<RedactedArtifact | undefined>): DetailGroup {
  return {
    title,
    summary,
    artifacts: artifacts.filter((artifact): artifact is RedactedArtifact => Boolean(artifact))
  };
}

/**
 * 供左侧 Run History 使用：query 截断摘要 + 当前 state。
 * 纯函数，不依赖既有导出，buildWorkbenchViewModel 行为保持不变。
 */
export function summarizeTurn(turn: ChatTurn): { label: string; state: string } {
  const label = turn.query.trim().length > 20 ? `${turn.query.trim().slice(0, 20)}…` : turn.query.trim();
  return {
    label: label || "新对话",
    state: turn.error ? "失败" : turn.snapshot?.state ?? (turn.isRunning ? "running" : "等待运行")
  };
}

/**
 * 供 Session History 使用：session 首轮 query 截断 + 末轮 state。
 */
export function summarizeSession(session: Session): { label: string; state: string } {
  const firstTurn = session.turns[0];
  const label = firstTurn
    ? (firstTurn.query.trim().length > 20 ? `${firstTurn.query.trim().slice(0, 20)}…` : firstTurn.query.trim())
    : "新对话";
  const lastTurn = session.turns[session.turns.length - 1];
  const state = lastTurn
    ? (lastTurn.error ? "失败" : lastTurn.snapshot?.state ?? (lastTurn.isRunning ? "running" : "完成"))
    : "等待运行";
  return { label: label || "新对话", state };
}

/**
 * 单轮 AI 气泡的渲染态：是否已有 narrative 正文、是否显示流式光标占位。
 * 抽成纯函数以便单测覆盖 spec 的「流式占位 -> narrative 切换」场景。
 */
export type ChatBubbleState = {
  hasNarrative: boolean;
  showStreaming: boolean;
  placeholder: string;
};

export function buildChatBubbleState(turn: ChatTurn): ChatBubbleState {
  const view = buildWorkbenchViewModel(turn.snapshot);
  const hasNarrative =
    turn.snapshot !== null && view.result.tone !== "running" && view.result.tone !== "idle";
  const showStreaming = turn.isRunning && !hasNarrative;
  return {
    hasNarrative,
    showStreaming,
    placeholder: showStreaming
      ? "正在推理"
      : "输入问题后，我会按 Harness 链路展示意图、能力、CallPlan、Gateway、事实与 Trace。"
  };
}

/**
 * S2-A 只读五态决策视图（Design Doc §Workbench 前端）。
 *
 * 从 snapshot 中提取 `match-decision` artifact 并构造渲染用的视图模型。
 * SSE 层只在 SHOW_OPTIONS / ESCALATE_TO_PLANNER 时发射该 artifact
 * （SELECT / CLARIFY / REJECT 复用现有 capability_selected / narrative_created
 * / run_failed 路径），但本函数对五种 decisionType 均做防御性解析，
 * 以便未来 artifact 协议扩展时不破坏渲染。
 *
 * 纯函数，无副作用；输入为 null 或 artifact 缺失/畸形时返回 null。
 */
export function buildMatchDecisionView(snapshot: AgentRunSnapshot | null): MatchDecisionView | null {
  if (!snapshot) {
    return null;
  }
  const artifact = snapshot.events.find((event) => event.artifact?.kind === "match-decision")?.artifact;
  if (!artifact) {
    return null;
  }
  const payload = artifact.payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const record = payload as Record<string, JsonValue>;
  const decisionType = record.decisionType;
  if (typeof decisionType !== "string") {
    return null;
  }
  if (
    decisionType !== "SELECT" &&
    decisionType !== "CLARIFY" &&
    decisionType !== "REJECT" &&
    decisionType !== "SHOW_OPTIONS" &&
    decisionType !== "ESCALATE_TO_PLANNER"
  ) {
    return null;
  }
  const candidates = parseCandidates(record.candidates);
  const handoff = parseHandoff(record.handoff);
  const rationale = typeof record.rationale === "string" ? record.rationale : "";

  const view: MatchDecisionView = {
    decisionType,
    rationale
  };
  if (candidates) {
    view.candidates = candidates;
  }
  if (handoff) {
    view.handoff = handoff;
  }
  return view;
}

function parseCandidates(value: JsonValue): MatchDecisionCandidate[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const candidates: MatchDecisionCandidate[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      continue;
    }
    const rec = entry as Record<string, JsonValue>;
    const capabilityId = typeof rec.capabilityId === "string" ? rec.capabilityId : "";
    if (!capabilityId) {
      continue;
    }
    const parameters = parseStringRecord(rec.parameters);
    const missing = parseStringArray(rec.missing);
    candidates.push({ capabilityId, parameters, missing });
  }
  return candidates.length > 0 ? candidates : undefined;
}

function parseHandoff(value: JsonValue): MatchDecisionHandoff | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const rec = value as Record<string, JsonValue>;
  const reason = typeof rec.reason === "string" ? rec.reason : "";
  const utterance = typeof rec.utterance === "string" ? rec.utterance : "";
  const registrySnapshotId = typeof rec.registrySnapshotId === "string" ? rec.registrySnapshotId : "";
  const matchedIntents = parseCandidates(rec.matchedIntents) ?? [];
  if (!reason && !utterance && !registrySnapshotId && matchedIntents.length === 0) {
    return undefined;
  }
  return { reason, matchedIntents, utterance, registrySnapshotId };
}

function parseStringRecord(value: JsonValue): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const out: Record<string, string> = {};
  for (const [key, entry] of Object.entries(value as Record<string, JsonValue>)) {
    if (typeof entry === "string" || typeof entry === "number" || typeof entry === "boolean") {
      out[key] = String(entry);
    }
  }
  return out;
}

function parseStringArray(value: JsonValue): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is string => typeof entry === "string");
}

// ---- S2-B dry-run preview (Task 9) ----

/**
 * S2-B dry-run 预览视图（Design Doc §Workbench 前端 D6 / §dry-run 输出）。
 *
 * 从 snapshot 中提取 `match-decision` artifact 并解析其中的 `dryRun`
 * 字段（由 SSE adapter 从 outcome.dryRun 折叠进 payload）。返回渲染用的
 * `DryRunView`，包含 PlanGraph 节点/边/参数来源/缺口/治理标记。
 *
 * 纯函数，无副作用；输入为 null、artifact 缺失或 payload 畸形时返回 null。
 * dry-run 是只读预览，不发起 Gateway/SAP 调用。
 */
export function buildDryRunView(snapshot: AgentRunSnapshot | null): DryRunView | null {
  if (!snapshot) {
    return null;
  }
  const artifact = snapshot.events.find((event) => event.artifact?.kind === "match-decision")?.artifact;
  if (!artifact) {
    return null;
  }
  const payload = artifact.payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const record = payload as Record<string, JsonValue>;
  const dryRunRaw = record.dryRun;
  if (!dryRunRaw || typeof dryRunRaw !== "object" || Array.isArray(dryRunRaw)) {
    return null;
  }
  const dryRun = dryRunRaw as Record<string, JsonValue>;
  const planGraph = parsePlanGraph(dryRun.planGraph);
  if (!planGraph) {
    return null;
  }
  const gaps = parseGaps(dryRun.gaps);
  const governanceFlags = parseFlags(dryRun.governanceFlags);
  const rationale = typeof dryRun.rationale === "string" ? dryRun.rationale : "";
  return { planGraph, gaps, governanceFlags, rationale };
}

function parsePlanGraph(value: JsonValue): DryRunPlanGraph | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const rec = value as Record<string, JsonValue>;
  const planId = typeof rec.planId === "string" ? rec.planId : "";
  const goalId = typeof rec.goalId === "string" ? rec.goalId : "";
  const executionMode = typeof rec.executionMode === "string" ? rec.executionMode : "";
  const snapshotId = typeof rec.snapshotId === "string" ? rec.snapshotId : undefined;
  const nodes = parsePlanNodes(rec.nodes);
  const edges = Array.isArray(rec.edges) ? rec.edges : [];
  const topologicalOrder = parseStringArray(rec.topologicalOrder);
  const goalOutputs = parseGoalOutputs(rec.goalOutputs);
  if (!planId && !goalId && nodes.length === 0) {
    return null;
  }
  return { planId, goalId, executionMode, snapshotId, nodes, edges, topologicalOrder, goalOutputs };
}

function parsePlanNodes(value: JsonValue): DryRunPlanNode[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const nodes: DryRunPlanNode[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      continue;
    }
    const rec = entry as Record<string, JsonValue>;
    const nodeId = typeof rec.nodeId === "string" ? rec.nodeId : "";
    const capabilityId = typeof rec.capabilityId === "string" ? rec.capabilityId : "";
    if (!nodeId && !capabilityId) {
      continue;
    }
    const parameterBindings = parseParameterBindings(rec.parameterBindings);
    const producesFactTypes = parseStringArray(rec.producesFactTypes);
    nodes.push({ nodeId, capabilityId, parameterBindings, producesFactTypes });
  }
  return nodes;
}

function parseParameterBindings(value: JsonValue): DryRunParameterBinding[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const bindings: DryRunParameterBinding[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      continue;
    }
    const rec = entry as Record<string, JsonValue>;
    const parameterName = typeof rec.parameterName === "string" ? rec.parameterName : "";
    if (!parameterName) {
      continue;
    }
    const sourceRaw = rec.source;
    const source =
      sourceRaw && typeof sourceRaw === "object" && !Array.isArray(sourceRaw)
        ? (sourceRaw as Record<string, JsonValue>)
        : null;
    if (!source) {
      continue;
    }
    const kind = typeof source.kind === "string" ? source.kind : "";
    if (!kind) {
      continue;
    }
    const constraintName =
      typeof source.constraintName === "string" ? source.constraintName : undefined;
    bindings.push({ parameterName, source: { kind, constraintName } });
  }
  return bindings;
}

function parseGoalOutputs(value: JsonValue): DryRunGoalOutput[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const outputs: DryRunGoalOutput[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      continue;
    }
    const rec = entry as Record<string, JsonValue>;
    const factTypeId = typeof rec.factTypeId === "string" ? rec.factTypeId : "";
    const producerNodeId =
      typeof rec.producerNodeId === "string" ? rec.producerNodeId : "";
    if (!factTypeId && !producerNodeId) {
      continue;
    }
    outputs.push({ factTypeId, producerNodeId });
  }
  return outputs;
}

function parseGaps(value: JsonValue): DryRunGap[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const gaps: DryRunGap[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      continue;
    }
    const rec = entry as Record<string, JsonValue>;
    const kind = typeof rec.kind === "string" ? rec.kind : "";
    const detail = typeof rec.detail === "string" ? rec.detail : "";
    if (!kind && !detail) {
      continue;
    }
    gaps.push({ kind, detail });
  }
  return gaps;
}

function parseFlags(value: JsonValue): DryRunFlag[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const flags: DryRunFlag[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      continue;
    }
    const rec = entry as Record<string, JsonValue>;
    const kind = typeof rec.kind === "string" ? rec.kind : "";
    const detail = typeof rec.detail === "string" ? rec.detail : "";
    if (!kind && !detail) {
      continue;
    }
    flags.push({ kind, detail });
  }
  return flags;
}
