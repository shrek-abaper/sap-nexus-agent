"use client";

import { useState } from "react";
import type { AgentRunEvent, AgentRunSnapshot } from "@/runtime/run-event-schema";
import { applyRunEvent, createInitialSnapshot } from "@/runtime/run-state-machine";
import { ChatStream } from "./ChatStream";
import { ChatComposer } from "./ChatComposer";
import { summarizeTurn } from "./view-model";
import type { ChatTurn, ActiveTurnIndex } from "./chat-types";
import { Icon, type IconName } from "@/shared/ui/Icon";

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
  "run_failed"
] satisfies AgentRunEvent["type"][];

const navItems: { label: string; icon: IconName }[] = [
  { label: "首页", icon: "home" },
  { label: "能力本体注册", icon: "functionFilled" },
  { label: "能力目录", icon: "catalogue" },
  { label: "Trace 审计", icon: "record" },
  { label: "Gateway", icon: "route" },
  { label: "设置", icon: "setting" }
];

const quickPrompts = [
  "DEMOA2 在 5100 还有多少可用库存？",
  "P0001529AC 在 1000 还有多少可用库存？",
  "查下PO DEMOPO2"
];

const nextRunId = (turns: ChatTurn[]) => `run-${turns.length + 1}`;

export function AgentConsole() {
  const [query, setQuery] = useState("DEMOA1 在 1000 还有多少可用库存？");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [activeIndex, setActiveIndex] = useState<ActiveTurnIndex>(null);

  const hasRun = turns.length > 0;

  function streamAgentRun(
    localRunId: string,
    serverRunId: string,
    initialSnapshot: AgentRunSnapshot
  ) {
    let nextSnapshot = initialSnapshot;
    let intentionallyClosed = false;
    const stream = new EventSource(`/api/agent-runs/${serverRunId}/stream`);
    const handleRunEvent = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as AgentRunEvent;
      if (nextSnapshot.events.some((existing) => existing.sequence === event.sequence)) {
        return;
      }
      nextSnapshot = applyRunEvent(nextSnapshot, event);
      setTurns((prev) =>
        prev.map((turn) => (turn.runId === localRunId ? { ...turn, snapshot: nextSnapshot } : turn))
      );
      const pausedForApproval = event.state === "awaiting_approval";
      const terminal = event.state === "completed" || event.state === "failed" || event.state === "rejected";
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
      setTurns((prev) =>
        prev.map((turn) =>
          turn.runId === localRunId
            ? { ...turn, isRunning: false, error: "连接中断，未能获取完整运行结果" }
            : turn
        )
      );
    };
  }

  async function decideApproval(serverRunId: string, decision: "approve" | "reject") {
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
        body: JSON.stringify({ decision })
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { message?: string } | null;
        throw new Error(body?.message ?? `审批请求失败（HTTP ${response.status}）`);
      }
      streamAgentRun(target.runId, serverRunId, target.snapshot);
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
        body: JSON.stringify({ query: trimmed })
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
        <div className="topbar-module">Governed Read / Write</div>
        <div className="topbar-search">
          <Icon name="search" size={16} />
          <span>全局检索 / Trace ID</span>
        </div>
      </header>

      <div className="workspace">
        <nav className="side-nav" aria-label="Workbench navigation">
          {navItems.map((item) => (
            <button
              className={`side-nav__item ${item.label === "首页" ? "is-active" : "is-disabled"}`}
              key={item.label}
              onClick={() => {
                if (item.label === "首页") {
                  setTurns([]);
                  setActiveIndex(null);
                }
              }}
              type="button"
            >
              <Icon name={item.icon} size={20} className="side-nav__icon" />
              <span>{item.label}</span>
              {item.label !== "首页" ? <em>soon</em> : null}
            </button>
          ))}

          <div className="side-nav__section">
            <div className="side-nav__label">Run History</div>
            {turns.length === 0 ? (
              <button className="history-item is-active" type="button">
                <span>暂无对话</span>
                <small>等待运行</small>
              </button>
            ) : (
              turns
                .map((turn, index) => ({ turn, index }))
                .reverse()
                .map(({ turn, index }) => {
                  const summary = summarizeTurn(turn);
                  return (
                    <button
                      className={`history-item ${activeIndex === index ? "is-active" : ""}`}
                      key={turn.runId}
                      onClick={() => setActiveIndex(index)}
                      type="button"
                    >
                      <span>{summary.label}</span>
                      <small>{summary.state}</small>
                    </button>
                  );
                })
            )}
          </div>

          <div className="side-nav__user">
            <div className="avatar">SN</div>
            <div>
              <strong>Agent Operator</strong>
              <span>Internal Console</span>
            </div>
          </div>
        </nav>

        <main className={`stage ${hasRun ? "stage--chat" : "stage--home"}`}>
          {!hasRun ? (
            <section className="home-hero">
              <p className="eyebrow">智能查询 / 原子能力工作台</p>
              <h1>用自然语言触发受控 SAP 能力，先看结论，再追溯证据链。</h1>
              <p>
                Read capability 直接执行；sandbox Action 必须先展示参数快照并由人工明确批准，才会进入 Gateway。
              </p>
              <form
                className="hero-query"
                onSubmit={(event) => {
                  event.preventDefault();
                  void runAgent();
                }}
              >
                <textarea value={query} onChange={(event) => setQuery(event.target.value)} />
                <div className="hero-query__footer">
                  <button disabled={false} type="submit">
                    发送
                  </button>
                </div>
              </form>
              <div className="quick-prompts">
                {quickPrompts.map((prompt) => (
                  <button key={prompt} onClick={() => setQuery(prompt)} type="button">
                    {prompt}
                  </button>
                ))}
              </div>
            </section>
          ) : (
            <>
              <ChatStream
                turns={turns}
                activeIndex={activeIndex}
                onApprovalDecision={(serverRunId, decision) => void decideApproval(serverRunId, decision)}
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
