"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatTurn, ActiveTurnIndex } from "./chat-types";
import {
  buildWorkbenchViewModel,
  buildChatBubbleState,
  buildMatchDecisionView,
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
  onApprovalDecision: (serverRunId: string, decision: "approve" | "reject") => void;
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
          ? [...turn.snapshot.events].reverse().find((event) => event.artifact?.kind === "approval")?.artifact
          : undefined;
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
                  onDecision={(decision) => onApprovalDecision(turn.snapshot!.runId, decision)}
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
 */
function MatchDecisionPanel({ snapshot }: { snapshot: AgentRunSnapshot }) {
  const view = buildMatchDecisionView(snapshot);
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
 * 过程证据折叠：操作行内的按钮 + 展开内容（timeline / 人审 / trace / 产物）。
 * Fragment 返回按钮与展开块；展开块 flex-basis 100% 自然换行到操作行下方。
 */
function EvidencePanel({ snapshot, view }: { snapshot: AgentRunSnapshot; view: WorkbenchViewModel }) {
  const [open, setOpen] = useState(false);
  const approvalArtifact = [...snapshot.events]
    .reverse()
    .find((event) => event.artifact?.kind === "approval")?.artifact;
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
          <section className="panel timeline-panel">
            <div className="section-title">
              <h2>Runtime Timeline</h2>
              <span>{snapshot.events.length} events</span>
            </div>
            <RuntimeTimeline events={snapshot.events} />
          </section>
          <HumanApprovalPanel state={snapshot.hitlState} artifact={approvalArtifact} />
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
