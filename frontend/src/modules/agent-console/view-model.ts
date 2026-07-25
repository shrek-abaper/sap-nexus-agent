import type { AgentRunEvent, AgentRunSnapshot } from "@/runtime/run-event-schema";
import type { JsonValue, RedactedArtifact } from "@/shared/types/artifacts";
import type { ChatTurn } from "./chat-types";

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
