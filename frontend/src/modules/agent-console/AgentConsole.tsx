"use client";

import { useState } from "react";
import type { AgentRunEvent, AgentRunSnapshot } from "@/runtime/run-event-schema";
import { applyRunEvent, createInitialSnapshot } from "@/runtime/run-state-machine";
import { ChatStream } from "./ChatStream";
import { ChatComposer } from "./ChatComposer";
import { summarizeSession } from "./view-model";
import type { ChatTurn, ActiveTurnIndex, Session } from "./chat-types";
import { createConversationId } from "./conversation-id";
import { Icon, type IconName } from "@/shared/ui/Icon";
import { samplePrompts, heroInputPlaceholder } from "./sample-data";
import { buildStreamUrl, lastEventSequence, RECONNECT_DELAY } from "./stream-helpers";

const agentRunEventTypes = [
  "run_started",
  "intent_parsed",
  "capability_selected",
  "callplan_created",
  "approval_state_changed",
  "gateway_validate_started",
  "gateway_validate_completed",
  "gateway_execute_started",
  "gateway_execute_completed",
  "reasoning_fact_created",
  "narrative_created",
  "trace_linked",
  "run_completed",
  "run_failed",
  "match_decision_created",
  "batch_confirm_requested",
  "node_state_changed",
  "intent_recognized",
  "capability_recalled",
  "plan_compiled",
  "plan_node_state",
  "fact_emitted",
  "projection_completed",
  "recommendation_completed",
  "narrative_completed",
  "action_proposed",
  "approval_updated",
  "action_executed"
] satisfies AgentRunEvent["type"][];

const navItems: { id: string; label: string; icon: IconName }[] = [
  { id: "capability-registry", label: "能力本体注册", icon: "functionFilled" },
  { id: "capability-catalogue", label: "能力目录", icon: "catalogue" },
  { id: "trace-audit", label: "Trace 审计", icon: "record" },
  { id: "gateway", label: "Gateway", icon: "route" }
];

const nextRunId = (turns: ChatTurn[]) => `run-${turns.length + 1}`;

export function AgentConsole() {
  const [query, setQuery] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [activeIndex, setActiveIndex] = useState<ActiveTurnIndex>(null);
  const [conversationId, setConversationId] = useState<string>(createConversationId);
  const [sessions, setSessions] = useState<Session[]>([]);

  function switchToSession(session: Session) {
    if (turns.length > 0) {
      setSessions((prev) => [...prev, { conversationId, turns }]);
    }
    setSessions((prev) => prev.filter((s) => s.conversationId !== session.conversationId));
    setTurns(session.turns);
    setConversationId(session.conversationId);
    setActiveIndex(null);
  }

  const hasRun = turns.length > 0;

  function streamAgentRun(
    localRunId: string,
    serverRunId: string,
    initialSnapshot: AgentRunSnapshot,
    cursor = 0
  ) {
    let nextSnapshot = initialSnapshot;
    let lastSequence = cursor;
    let intentionallyClosed = false;
    const stream = new EventSource(buildStreamUrl(serverRunId, cursor));
    const handleRunEvent = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as AgentRunEvent;
      lastSequence = Math.max(lastSequence, event.sequence);
      nextSnapshot = applyRunEvent(nextSnapshot, event);
      setTurns((prev) =>
        prev.map((turn) => (turn.runId === localRunId ? { ...turn, snapshot: nextSnapshot } : turn))
      );
      // Approval pause is 2 sequential SSE events sharing state:"awaiting_approval"
      // (hitlState approval_required, then awaiting_human_approval + the
      // ApprovalRecord artifact; see emitEventsFromOutcome). Gating close on
      // `state` races the 2nd event since the server awaits a store append
      // between the two writes - the client can close after the 1st and
      // never see the artifact the panel needs. Gate on hitlState instead.
      const pausedForApproval = nextSnapshot.hitlState === "awaiting_human_approval";
      const terminal = nextSnapshot.state === "completed" || nextSnapshot.state === "failed" || nextSnapshot.state === "rejected";
      if (pausedForApproval || terminal) {
        intentionallyClosed = true;
        stream.close();
        setTurns((prev) =>
          prev.map((turn) => (turn.runId === localRunId ? { ...turn, isRunning: false } : turn))
        );
      }
    };
    stream.onmessage = handleRunEvent;
    agentRunEventTypes.forEach((eventType) => stream.addEventListener(eventType, handleRunEvent));
    stream.onerror = () => {
      stream.close();
      if (intentionallyClosed) {
        return;
      }
      // §6.1: reconnect with cursor to resume from last received event
      setTimeout(() => {
        streamAgentRun(localRunId, serverRunId, nextSnapshot, lastSequence);
      }, RECONNECT_DELAY);
    };
  }

  async function decideApproval(
    serverRunId: string,
    approvalId: string,
    decision: "approve" | "reject"
  ) {
    const target = turns.find((turn) => turn.snapshot?.runId === serverRunId);
    if (!target?.snapshot) {
      return;
    }
    setTurns((prev) =>
      prev.map((turn) =>
        turn.runId === target.runId ? { ...turn, isRunning: true, error: undefined } : turn
      )
    );
    try {
      const response = await fetch(`/api/agent-runs/${serverRunId}/approval`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approvalId, decision })
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { message?: string } | null;
        throw new Error(body?.message ?? `审批请求失败（HTTP ${response.status}）`);
      }
      const cursor = lastEventSequence(target.snapshot.events);
      streamAgentRun(target.runId, serverRunId, target.snapshot, cursor);
    } catch (error) {
      const message = error instanceof Error ? error.message : "审批请求失败";
      setTurns((prev) =>
        prev.map((turn) =>
          turn.runId === target.runId ? { ...turn, isRunning: false, error: message } : turn
        )
      );
    }
  }

  async function runAgent() {
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }
    const runId = nextRunId(turns);
    const newTurn: ChatTurn = { runId, query: trimmed, snapshot: null, isRunning: true };
    setTurns((prev) => [...prev, newTurn]);
    setActiveIndex(turns.length);
    setQuery("");

    let serverRunId: string;
    try {
      const response = await fetch("/api/agent-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: trimmed, conversationId })
      });
      if (!response.ok) {
        const errorBody = (await response.json().catch(() => null)) as { message?: string } | null;
        throw new Error(errorBody?.message ?? `请求失败（HTTP ${response.status}）`);
      }
      const data = (await response.json()) as { runId?: string };
      if (!data.runId) {
        throw new Error("服务端未返回 runId");
      }
      serverRunId = data.runId;
    } catch (error) {
      const message = error instanceof Error ? error.message : "请求失败，未能发起查询";
      setTurns((prev) =>
        prev.map((turn) => (turn.runId === runId ? { ...turn, isRunning: false, error: message } : turn))
      );
      return;
    }

    const nextSnapshot = createInitialSnapshot(serverRunId);
    setTurns((prev) =>
      prev.map((turn) => (turn.runId === runId ? { ...turn, snapshot: nextSnapshot } : turn))
    );
    streamAgentRun(runId, serverRunId, nextSnapshot);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark">
          <Icon name="aiAgent" size={20} />
        </div>
        <div>
          <div className="brand-name">SAP Nexus Agent</div>
          <div className="brand-subtitle">Harness Engineering Workbench</div>
        </div>
        <div className="topbar-module">
          <span className="topbar-module__dot topbar-module__dot--read" aria-hidden="true" />
          Read 直连
          <span className="topbar-module__sep" aria-hidden="true">·</span>
          <span className="topbar-module__dot topbar-module__dot--write" aria-hidden="true" />
          Write 需审批
        </div>
        <div className="topbar-search">
          <Icon name="search" size={16} />
          <span>全局检索 / Trace ID</span>
        </div>
      </header>

      <div className="workspace">
        <nav className="side-nav" aria-label="Workbench navigation">
          <button
            className="side-nav__cta"
            type="button"
            onClick={() => {
              if (turns.length > 0) {
                setSessions((prev) => [...prev, { conversationId, turns }]);
              }
              setTurns([]);
              setActiveIndex(null);
              setConversationId(createConversationId());
            }}
          >
            <Icon name="plus" size={18} className="side-nav__cta-icon" />
            <span>新对话</span>
          </button>

          <div className="side-nav__group">
            {navItems.map((item) => (
              <button className="side-nav__item is-disabled" key={item.id} type="button" disabled>
                <Icon name={item.icon} size={20} className="side-nav__icon" />
                <span>{item.label}</span>
                <em>soon</em>
              </button>
            ))}
          </div>

          <div className="side-nav__section">
            <div className="side-nav__label">Session History</div>
            {turns.length === 0 && sessions.length === 0 ? (
              <button className="history-item is-active" type="button">
                <span>暂无对话</span>
                <small>等待运行</small>
              </button>
            ) : (
              <>
                {turns.length > 0 && (
                  <button className="history-item is-active" type="button">
                    <span>{summarizeSession({ conversationId, turns }).label}</span>
                    <small>{summarizeSession({ conversationId, turns }).state}</small>
                  </button>
                )}
                {sessions.slice().reverse().map((session) => {
                  const summary = summarizeSession(session);
                  return (
                    <button
                      className="history-item"
                      key={session.conversationId}
                      onClick={() => switchToSession(session)}
                      type="button"
                    >
                      <span>{summary.label}</span>
                      <small>{summary.state}</small>
                    </button>
                  );
                })}
              </>
            )}
          </div>

          <div className="side-nav__user">
            <div className="avatar">SN</div>
            <div className="side-nav__user-meta">
              <strong>Agent Operator</strong>
              <span>Internal Console</span>
            </div>
            <button className="side-nav__user-action" type="button" aria-label="设置" disabled>
              <Icon name="setting" size={18} />
            </button>
          </div>
        </nav>

        <main className={`stage ${hasRun ? "stage--chat" : "stage--home"}`}>
          {!hasRun ? (
            <section className="home-hero">
              <p className="eyebrow">智能查询 / 原子能力工作台</p>
              <h1>用自然语言调用受控 SAP 能力</h1>
              <p className="home-hero__subtitle">先给结论，再给证据链</p>
              <form
                className="hero-query"
                onSubmit={(event) => {
                  event.preventDefault();
                  void runAgent();
                }}
              >
                <textarea
                  placeholder={heroInputPlaceholder}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void runAgent();
                    }
                  }}
                />
                <div className="hero-query__footer">
                  <span className="hero-query__guard">未声明的能力不会执行 · 写操作需人工批准</span>
                  <button disabled={false} type="submit">
                    发送
                  </button>
                </div>
              </form>
              <div className="quick-prompts">
                {samplePrompts.map((prompt) => (
                  <button
                    className={`quick-prompt quick-prompt--${prompt.kind}`}
                    key={prompt.label}
                    onClick={() => setQuery(prompt.query)}
                    type="button"
                  >
                    <span className="quick-prompt__label">{prompt.label}</span>
                    <span className="quick-prompt__text">
                      {prompt.segments.map((segment, index) =>
                        segment.mono ? (
                          <span className="mono-token" key={index}>
                            {segment.text}
                          </span>
                        ) : (
                          <span key={index}>{segment.text}</span>
                        )
                      )}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          ) : (
            <>
              <ChatStream
                turns={turns}
                activeIndex={activeIndex}
                onApprovalDecision={(serverRunId, approvalId, decision) => void decideApproval(serverRunId, approvalId, decision)}
              />
              <ChatComposer
                value={query}
                onChange={setQuery}
                onSubmit={() => void runAgent()}
                isRunning={turns.some((turn) => turn.isRunning)}
              />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
