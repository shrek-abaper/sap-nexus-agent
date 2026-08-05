"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatTurn, ActiveTurnIndex } from "./chat-types";
import {
  buildWorkbenchViewModel,
  buildChatBubbleState,
  buildMatchDecisionView,
  buildDryRunView,
  type DryRunGap,
  type DryRunFlag,
  type DryRunParameterBinding,
  type DryRunPlanNode,
  type DryRunView,
  type MatchDecisionCandidate,
  type MatchDecisionHandoff,
  type MatchDecisionView,
  type WorkbenchResultTone,
  type WorkbenchViewModel,
  type ReasoningStep
} from "./view-model";
import type { AgentRunSnapshot } from "@/runtime/run-event-schema";
import { RuntimeTimeline } from "@/modules/runtime-timeline/RuntimeTimeline";
import { HumanApprovalPanel } from "@/modules/human-approval/HumanApprovalPanel";
import { TraceAuditPanel } from "@/modules/trace-audit/TraceAuditPanel";
import { ArtifactJson } from "@/shared/ui/ArtifactJson";
import { Icon } from "@/shared/ui/Icon";
import { PlanEvidencePanel } from "@/modules/plan-evidence/PlanEvidencePanel";

const resultToneLabel: Record<WorkbenchResultTone, string> = {
  idle: "待运行",
  running: "运行中",
  success: "已完成",
  clarification: "需澄清",
  failure: "运行失败"
};

const matchDecisionTypeLabel: Record<MatchDecisionView["decisionType"], string> = {
  SELECT: "已选定能力",
  CLARIFY: "需补充参数",
  REJECT: "拒绝执行",
  SHOW_OPTIONS: "候选能力待选",
  ESCALATE_TO_PLANNER: "转交规划层"
};

interface ChatStreamProps {
  turns: ChatTurn[];
  activeIndex: ActiveTurnIndex;
  onApprovalDecision: (
    serverRunId: string,
    approvalId: string,
    decision: "approve" | "reject"
  ) => void;
}

/**
 * 中间区域消息流：每轮问答聚合在同一个 Notion 式卡片内。
 * 卡片内：用户问题（顶部，带头像）-> 分隔线 -> AI 回复（role 标 + 折叠思考过程 + narrative 正文 + 操作行 + 折叠证据）。
 * reasoning 默认折叠，运行中自动展开，完成自动折叠。
 * 多轮消息常驻累积；点击 Run History 时滚动并高亮定位到对应轮。
 */
export function ChatStream({ turns, activeIndex, onApprovalDecision }: ChatStreamProps) {
  const turnRefs = useRef<Array<HTMLDivElement | null>>([]);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length]);

  useEffect(() => {
    if (activeIndex !== null && turnRefs.current[activeIndex]) {
      turnRefs.current[activeIndex]?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [activeIndex]);

  return (
    <div className="chat-stream">
      {turns.map((turn, turnIndex) => {
        const view = buildWorkbenchViewModel(turn.snapshot);
        const bubble = buildChatBubbleState(turn);
        const approvalArtifact = turn.snapshot
          ? [...turn.snapshot.events].reverse().find(
              (event) => event.artifact?.kind === "approval" || event.artifact?.kind === "approval-record"
            )?.artifact
          : undefined;
        const approvalId = approvalIdentity(approvalArtifact);
        return (
          <div
            className={`chat-turn chat-turn--card ${activeIndex === turnIndex ? "chat-turn--active" : ""}`}
            key={turn.runId}
            ref={(el) => {
              turnRefs.current[turnIndex] = el;
            }}
          >
            <div className="turn-question">
              <div className="turn-question__avatar">你</div>
              <p className="turn-question__text">{turn.query}</p>
            </div>

            <div className="turn-divider" />

            <div className={`turn-answer turn-answer--${turn.error ? "failure" : view.result.tone}`}>
              <div className="turn-answer__head">
                <Icon name="aiQa" size={16} />
                <span>SAP Nexus Agent · {turn.error ? "运行失败" : resultToneLabel[view.result.tone]}</span>
              </div>

              {view.reasoningSteps.length > 0 ? (
                <ReasoningCollapse
                  steps={view.reasoningSteps}
                  isRunning={turn.isRunning}
                  hasNarrative={bubble.hasNarrative}
                  runId={turn.runId}
                />
              ) : null}

              <p className="turn-answer__narrative">
                {turn.error ? (
                  <span className="turn-answer__error">{turn.error}</span>
                ) : bubble.hasNarrative ? (
                  view.result.body
                ) : bubble.showStreaming ? (
                  <span className="streaming-cursor">{bubble.placeholder}</span>
                ) : (
                  bubble.placeholder
                )}
              </p>

              {turn.snapshot ? <MatchDecisionPanel snapshot={turn.snapshot} /> : null}

              {turn.snapshot && turn.snapshot.hitlState !== "approval_not_required" ? (
                <HumanApprovalPanel
                  state={turn.snapshot.hitlState}
                  artifact={approvalArtifact}
                  disabled={turn.isRunning}
                  onDecision={approvalId
                    ? (decision) => onApprovalDecision(turn.snapshot!.runId, approvalId, decision)
                    : undefined}
                />
              ) : null}

              <div className="turn-actions">
                {bubble.hasNarrative ? <CopyButton text={view.result.body} /> : null}
                {turn.snapshot ? <EvidencePanel snapshot={turn.snapshot} view={view} /> : null}
              </div>
            </div>
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}

function approvalIdentity(artifact: import("@/shared/types/artifacts").RedactedArtifact | undefined): string {
  const envelope = artifact?.payload && typeof artifact.payload === "object" && !Array.isArray(artifact.payload)
    ? artifact.payload as Record<string, unknown>
    : undefined;
  const data = envelope?.data && typeof envelope.data === "object" && !Array.isArray(envelope.data)
    ? envelope.data as Record<string, unknown>
    : envelope;
  const value = data?.approvalId ?? data?.id;
  return typeof value === "string" ? value : "";
}

/**
 * 思考过程折叠：默认折叠，运行中自动展开，完成自动折叠（Notion 风格）。
 * 用户可随时手动切换。
 */
function ReasoningCollapse({
  steps,
  isRunning,
  hasNarrative,
  runId
}: {
  steps: ReasoningStep[];
  isRunning: boolean;
  hasNarrative: boolean;
  runId: string;
}) {
  const [open, setOpen] = useState(isRunning && !hasNarrative);
  const prevRunning = useRef(isRunning);

  useEffect(() => {
    if (prevRunning.current && !isRunning) {
      setOpen(false);
    }
    prevRunning.current = isRunning;
  }, [isRunning]);

  const live = isRunning && !hasNarrative;

  return (
    <div className="reasoning-collapse">
      <button
        className="reasoning-collapse__summary"
        onClick={() => setOpen((o) => !o)}
        type="button"
        aria-expanded={open}
      >
        <span className={`reasoning-collapse__arrow ${open ? "is-open" : ""}`}>▸</span>
        <span>思考过程 · {steps.length} 步</span>
        {live ? <small className="reasoning-collapse__live">进行中</small> : null}
      </button>
      {open ? (
        <div className="reasoning-card">
          {steps.map((step) => (
            <div className={`reasoning-step reasoning-step--${step.status}`} key={`${runId}-${step.sequence}`}>
              <span>{step.sequence.toString().padStart(2, "0")}</span>
              <strong>{step.label}</strong>
              <small>{step.state}</small>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="turn-action"
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard 不可用时静默 */
        }
      }}
    >
      {copied ? "已复制" : "复制"}
    </button>
  );
}

/**
 * S2-A 匹配决策只读面板（Design Doc §Workbench 前端）。
 *
 * 当 turn snapshot 含 `match-decision` artifact（SHOW_OPTIONS /
 * ESCALATE_TO_PLANNER 时由 SSE 发射）时，在 turn 卡片内折叠展示
 * 候选能力或转交规划层信息。纯只读，不发起 Gateway/SAP 调用。
 * SELECT / CLARIFY / REJECT 走现有事件路径，本面板仅在 artifact 存在时渲染。
 *
 * S2-B (Task 9): 当 ESCALATE turn 同时携带 dryRun 时，在 handoff 下方
 * 追加 dry-run 预览折叠（PlanGraph 节点/参数来源/缺口/治理标记），
 * 标注"dry-run 预览，不执行 Gateway/SAP"。
 */
function MatchDecisionPanel({ snapshot }: { snapshot: AgentRunSnapshot }) {
  const view = buildMatchDecisionView(snapshot);
  const dryRunView = buildDryRunView(snapshot);
  const [open, setOpen] = useState(false);
  if (!view) {
    return null;
  }
  const label = matchDecisionTypeLabel[view.decisionType];
  return (
    <div className="match-decision">
      <button
        className="match-decision__summary"
        onClick={() => setOpen((o) => !o)}
        type="button"
        aria-expanded={open}
      >
        <span className={`match-decision__arrow ${open ? "is-open" : ""}`}>▸</span>
        <span>匹配决策 · {label}</span>
      </button>
      {open ? (
        <div className="match-decision__body">
          {view.rationale ? <p className="match-decision__rationale">{view.rationale}</p> : null}
          {view.candidates && view.candidates.length > 0 ? (
            <ul className="match-decision__candidates">
              {view.candidates.map((candidate: MatchDecisionCandidate) => (
                <li className="match-decision__candidate" key={candidate.capabilityId}>
                  <strong>{candidate.capabilityId}</strong>
                  {Object.keys(candidate.parameters).length > 0 ? (
                    <span className="match-decision__params">
                      {Object.entries(candidate.parameters)
                        .map(([key, value]) => `${key}=${value}`)
                        .join(", ")}
                    </span>
                  ) : null}
                  {candidate.missing.length > 0 ? (
                    <span className="match-decision__missing">缺参: {candidate.missing.join(", ")}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {view.handoff ? <MatchDecisionHandoffBlock handoff={view.handoff} /> : null}
          {dryRunView ? <DryRunPreviewBlock dryRun={dryRunView} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function MatchDecisionHandoffBlock({ handoff }: { handoff: MatchDecisionHandoff }) {
  return (
    <dl className="match-decision__handoff">
      <div>
        <dt>转交原因</dt>
        <dd>{handoff.reason || "—"}</dd>
      </div>
      <div>
        <dt>原 utterance</dt>
        <dd>{handoff.utterance || "—"}</dd>
      </div>
      <div>
        <dt>注册表快照</dt>
        <dd>{handoff.registrySnapshotId || "—"}</dd>
      </div>
      {handoff.matchedIntents.length > 0 ? (
        <div>
          <dt>命中意图</dt>
          <dd>
            <ul className="match-decision__candidates">
              {handoff.matchedIntents.map((intent) => (
                <li className="match-decision__candidate" key={intent.capabilityId}>
                  <strong>{intent.capabilityId}</strong>
                  {Object.keys(intent.parameters).length > 0 ? (
                    <span className="match-decision__params">
                      {Object.entries(intent.parameters)
                        .map(([key, value]) => `${key}=${value}`)
                        .join(", ")}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

/**
 * S2-B dry-run 预览折叠（Design Doc §Workbench 前端 D6 / §dry-run 输出）。
 *
 * 在 ESCALATE turn 的 handoff 下方折叠展示 PlanGraph 节点（capabilityId
 * + 参数来源）、缺口、治理标记。标注"dry-run 预览，不执行 Gateway/SAP"。
 * 纯只读，无执行按钮。
 */
function DryRunPreviewBlock({ dryRun }: { dryRun: DryRunView }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="dry-run-preview">
      <button
        className="dry-run-preview__summary"
        onClick={() => setOpen((o) => !o)}
        type="button"
        aria-expanded={open}
      >
        <span className={`dry-run-preview__arrow ${open ? "is-open" : ""}`}>▸</span>
        <span>dry-run 预览 · {dryRun.planGraph.nodes.length} 节点</span>
        <small className="dry-run-preview__badge">不执行 Gateway/SAP</small>
      </button>
      {open ? (
        <div className="dry-run-preview__body">
          {dryRun.rationale ? (
            <p className="dry-run-preview__rationale">{dryRun.rationale}</p>
          ) : null}
          <div className="dry-run-preview__plan-graph">
            <span className="dry-run-preview__section-label">PlanGraph 节点</span>
            <ul className="dry-run-preview__nodes">
              {dryRun.planGraph.nodes.map((node: DryRunPlanNode) => (
                <li className="dry-run-preview__node" key={node.nodeId || node.capabilityId}>
                  <strong>{node.capabilityId}</strong>
                  {node.producesFactTypes.length > 0 ? (
                    <span className="dry-run-preview__fact-types">
                      产出: {node.producesFactTypes.join(", ")}
                    </span>
                  ) : null}
                  {node.parameterBindings.length > 0 ? (
                    <ul className="dry-run-preview__bindings">
                      {node.parameterBindings.map((binding: DryRunParameterBinding) => (
                        <li className="dry-run-preview__binding" key={binding.parameterName}>
                          <span className="dry-run-preview__param-name">{binding.parameterName}</span>
                          <span className="dry-run-preview__source-kind">
                            来源: {binding.source.kind}
                            {binding.source.constraintName
                              ? ` (${binding.source.constraintName})`
                              : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
            {dryRun.planGraph.topologicalOrder.length > 0 ? (
              <p className="dry-run-preview__topo">
                <span className="dry-run-preview__section-label">拓扑序:</span>
                <span className="dry-run-preview__topo-list">
                  {dryRun.planGraph.topologicalOrder.join(" -> ")}
                </span>
              </p>
            ) : null}
          </div>
          {dryRun.gaps.length > 0 ? (
            <div className="dry-run-preview__gaps">
              <span className="dry-run-preview__section-label">缺口</span>
              <ul className="dry-run-preview__gap-list">
                {dryRun.gaps.map((gap: DryRunGap, index) => (
                  <li className="dry-run-preview__gap" key={`${gap.kind}-${index}`}>
                    <span className="dry-run-preview__gap-kind">{gap.kind}</span>
                    <span className="dry-run-preview__gap-detail">{gap.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {dryRun.governanceFlags.length > 0 ? (
            <div className="dry-run-preview__flags">
              <span className="dry-run-preview__section-label">治理标记</span>
              <ul className="dry-run-preview__flag-list">
                {dryRun.governanceFlags.map((flag: DryRunFlag, index) => (
                  <li className="dry-run-preview__flag" key={`${flag.kind}-${index}`}>
                    <span className="dry-run-preview__flag-kind">{flag.kind}</span>
                    <span className="dry-run-preview__flag-detail">{flag.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * 过程证据折叠：操作行内的按钮 + 展开内容（timeline / 人审 / trace / 产物）。
 * Fragment 返回按钮与展开块；展开块 flex-basis 100% 自然换行到操作行下方。
 */
function EvidencePanel({ snapshot, view }: { snapshot: AgentRunSnapshot; view: WorkbenchViewModel }) {
  const [open, setOpen] = useState(false);
  const approvalArtifact = [...snapshot.events]
    .reverse()
    .find((event) => event.artifact?.kind === "approval" || event.artifact?.kind === "approval-record")?.artifact;
  const hasProposal = snapshot.events.some((event) => event.artifact?.kind === "action-proposal");
  return (
    <>
      <button
        className="turn-action"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "收起过程证据" : "查看过程证据"}
        <small>· {snapshot.events.length} events</small>
      </button>
      {open ? (
        <div className="evidence-body">
          <PlanEvidencePanel snapshot={snapshot} />
          <section className="panel timeline-panel">
            <div className="section-title">
              <h2>Runtime Timeline</h2>
              <span>{snapshot.events.length} events</span>
            </div>
            <RuntimeTimeline events={snapshot.events} />
          </section>
          {approvalArtifact || !hasProposal ? (
            <HumanApprovalPanel state={snapshot.hitlState} artifact={approvalArtifact} />
          ) : null}
          <TraceAuditPanel
            agentTraceId={view.artifacts.agentTraceId}
            gatewayTraceId={view.artifacts.gatewayTraceId}
          />
          <section className="detail-stack">
            {view.detailGroups.map((group, index) => (
              <details className="detail-group" key={group.title} open={index < 1}>
                <summary>
                  <strong>{group.title}</strong>
                  <span>{group.summary}</span>
                </summary>
                <div className="artifact-grid">
                  {group.artifacts.length > 0 ? (
                    group.artifacts.map((artifact) => (
                      <ArtifactJson artifact={artifact} key={`${group.title}-${artifact.kind}`} />
                    ))
                  ) : (
                    <p className="muted">等待运行产物。</p>
                  )}
                </div>
              </details>
            ))}
          </section>
        </div>
      ) : null}
    </>
  );
}
