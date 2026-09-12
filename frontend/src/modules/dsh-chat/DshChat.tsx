"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createConversationId } from "../agent-console/conversation-id";
import { ToolCallCard } from "./ToolCallCard";
import { Markdown } from "./Markdown";
import { DshSidebar } from "./DshSidebar";
import type { ChatMessage, ConversationSummary, DshStreamEvent, DshToolCall } from "./types";

const SUGGESTIONS = [
  "DEMOA1 在 1000 工厂够不够用、在途多少？",
  "查客户 1000 的销售订单",
  "供应商 DEMOV1 的应付未清项，公司代码 1000",
  "物料需要补货：目标 100 件、9 月 30 日前、采购组 601",
];

export function DshChat() {
  const [conversationId, setConversationId] = useState(() => createConversationId());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const busyRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const mainRef = useRef<HTMLElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const stickToBottomRef = useRef(true);
  const lastMessageCount = useRef(0);

  const refreshConversations = useCallback(async () => {
    try {
      const response = await fetch("/api/dsh/conversations");
      if (response.ok) {
        const body = await response.json() as { conversations?: ConversationSummary[] };
        setConversations(body.conversations ?? []);
      }
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshConversations();
    // Focus the composer on first load.
    inputRef.current?.focus();
  }, [refreshConversations]);

  function handleNewConversation() {
    if (busyRef.current) return;
    setConversationId(createConversationId());
    setMessages([]);
    setError(null);
    setSidebarOpen(false);
  }

  async function handleSelectConversation(id: string) {
    if (busyRef.current || id === conversationId) {
      setSidebarOpen(false);
      return;
    }
    setError(null);
    try {
      const response = await fetch(`/api/dsh/conversations/${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json() as { messages?: Array<ChatMessage & { ts?: number }> };
      const history = (body.messages ?? []).map(({ ts: _ts, ...message }) => ({
        ...message,
        pending: false,
        settled: true,
      }));
      setConversationId(id);
      setMessages(history);
      stickToBottomRef.current = true;
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "加载历史会话失败");
    } finally {
      setSidebarOpen(false);
    }
  }

  async function handleDeleteConversation(id: string) {
    // Optimistically remove from the list; revert on failure.
    const previous = conversations;
    setConversations((list) => list.filter((item) => item.id !== id));
    try {
      const response = await fetch(`/api/dsh/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!response.ok && response.status !== 404) throw new Error(`HTTP ${response.status}`);
      if (id === conversationId) {
        setConversationId(createConversationId());
        setMessages([]);
      }
    } catch (deleteError) {
      setConversations(previous);
      setError(deleteError instanceof Error ? deleteError.message : "删除会话失败");
    }
  }

  // Track whether the user is reading near the bottom; only auto-scroll when
  // they have not scrolled up to inspect earlier output.
  function handleScroll() {
    const el = mainRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distanceFromBottom < 120;
  }

  // Pin to bottom when a new turn starts (user sent a message), even if they
  // had scrolled up before sending.
  useEffect(() => {
    if (messages.length !== lastMessageCount.current) {
      const addedTurn = messages.length - lastMessageCount.current >= 2;
      lastMessageCount.current = messages.length;
      if (addedTurn) stickToBottomRef.current = true;
    }
  }, [messages.length]);

  // Auto-scroll on content growth while streaming, if pinned to bottom.
  useLayoutEffect(() => {
    const el = mainRef.current;
    if (el && stickToBottomRef.current) {
      el.scrollTo({ top: el.scrollHeight });
    }
  }, [messages]);

  function patchAssistant(id: string, patch: (message: ChatMessage) => ChatMessage) {
    setMessages((previous) => previous.map((message) => (message.id === id ? patch(message) : message)));
  }

  async function send(content: string) {
    const trimmed = content.trim();
    if (!trimmed || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setText("");
    // Keep focus in the composer so the next message can be typed right away.
    requestAnimationFrame(() => inputRef.current?.focus());
    const assistantId = `a-${Date.now()}`;
    const userId = `u-${Date.now()}`;
    // Pin the new question at the TOP of the viewport on every send. The
    // answer expands downward without auto-scrolling; the user can scroll.
    stickToBottomRef.current = false;
    setMessages((previous) => [
      ...previous,
      { id: userId, role: "user", text: trimmed },
      { id: assistantId, role: "assistant", text: "", pending: true, trace: "", answerTrace: "", liveTools: [], settled: false },
    ]);
    requestAnimationFrame(() => {
      const main = mainRef.current;
      const node = main?.querySelector<HTMLElement>(`[data-msg-id="${userId}"]`);
      // Align the new question to the top of the scroll viewport.
      node?.scrollIntoView({ block: "start", behavior: "smooth" });
    });

    try {
      const response = await fetch(`/api/dsh/conversations/${encodeURIComponent(conversationId)}/messages/stream`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: trimmed }),
      });
      if (!response.ok || !response.body) {
        const body = await response.json().catch(() => null) as { message?: string } | null;
        throw new Error(body?.message ?? `HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const line = chunk.split("\n").find((item) => item.startsWith("data:"));
          if (!line) continue;
          const event = JSON.parse(line.slice(5).trim()) as DshStreamEvent;
          handleEvent(assistantId, event);
        }
      }
      patchAssistant(assistantId, (message) =>
        message.settled ? message : { ...message, pending: false, settled: true, text: message.text || "(无输出)" });
    } catch (sendError) {
      setMessages((previous) => previous.filter((message) => !message.pending));
      setError(sendError instanceof Error ? sendError.message : String(sendError));
    } finally {
      busyRef.current = false;
      setBusy(false);
      // Refresh the sidebar so this turn (including a brand-new conversation)
      // appears in the history list.
      void refreshConversations();
    }
  }

  function handleEvent(assistantId: string, event: DshStreamEvent) {
    switch (event.type) {
      case "delta":
        patchAssistant(assistantId, (message) => event.phase === "answer"
          ? { ...message, answerTrace: `${message.answerTrace ?? ""}${event.text}` }
          : { ...message, trace: `${message.trace ?? ""}${event.text}` });
        break;
      case "tool-start":
        patchAssistant(assistantId, (message) => {
          const tools = [...(message.liveTools ?? [])];
          tools.push({
            callId: event.callId,
            name: event.name,
            args: (typeof event.args === "object" && event.args !== null ? event.args : {}) as Record<string, unknown>,
            status: "running",
          });
          return { ...message, liveTools: tools };
        });
        break;
      case "tool-result":
        patchAssistant(assistantId, (message) => ({
          ...message,
          liveTools: (message.liveTools ?? []).map((tool) =>
            tool.callId === event.callId
              ? {
                  ...tool,
                  status: event.status,
                  result: event.result as DshToolCall["result"],
                  error: event.error,
                }
              : tool,
          ),
        }));
        break;
      case "final":
        patchAssistant(assistantId, (message) => ({
          ...message,
          pending: false,
          settled: true,
          text: event.output || message.trace || "(无输出)",
          toolCalls: event.toolCalls,
        }));
        break;
      case "error":
        setError(event.message);
        patchAssistant(assistantId, (message) => ({ ...message, pending: false, settled: true, error: event.message }));
        break;
    }
  }

  const composerBody = (
    <>
      <textarea
        ref={inputRef}
        className="dsh-input"
        value={text}
        placeholder="输入业务问题，Enter 发送 / Shift+Enter 换行"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void send(text);
          }
        }}
        rows={1}
      />
      <button type="button" className="dsh-send" disabled={busy || !text.trim()} onClick={() => send(text)} aria-label="发送">
        ↑
      </button>
    </>
  );

  return (
    <div className={`dsh-shell${collapsed ? " dsh-shell--collapsed" : ""}${sidebarOpen ? " dsh-shell--sidebar" : ""}`}>
      <DshSidebar
        conversations={conversations}
        currentId={conversationId}
        loading={historyLoading}
        onNewConversation={handleNewConversation}
        onSelect={handleSelectConversation}
        onDelete={(id) => void handleDeleteConversation(id)}
        onCollapse={() => setCollapsed(true)}
      />

      {/* Expand affordance: rail column is 0 when collapsed. */}
      {collapsed ? (
        <button
          type="button"
          className="dsh-rail-expand"
          onClick={() => setCollapsed(false)}
          aria-label="展开侧栏"
          title="展开侧栏"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect width="18" height="18" x="3" y="3" rx="2" />
            <path d="M15 3v18" />
          </svg>
        </button>
      ) : null}

      <div className="dsh-content">
        <div className="dsh-topbar">
          <button
            type="button"
            className="dsh-menu"
            aria-label="切换会话列表"
            onClick={() => setSidebarOpen((open) => !open)}
          >
            ☰
          </button>
        </div>

        <main ref={mainRef} className={`dsh-main${messages.length === 0 ? " dsh-main--welcome" : ""}`} onScroll={handleScroll}
          onClick={() => sidebarOpen && setSidebarOpen(false)}>
        {messages.length === 0 ? (
          <div className="dsh-empty">
            <div className="dsh-empty__logo" aria-hidden>◆</div>
            <h2 className="dsh-empty__title">有什么可以帮你？</h2>
            <p>以自然语言问事实，以人工审批落行动。</p>
            {/* Composer first, suggestion cards underneath (dsh-web style). */}
            <div className="dsh-composer dsh-composer--welcome">
              <div className="dsh-composer-inner">{composerBody}</div>
            </div>
            <div className="dsh-suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button key={suggestion} type="button" className="dsh-suggestion" onClick={() => send(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div className="dsh-messages">
          {messages.map((message) => {
            const tools = message.toolCalls ?? message.liveTools ?? [];
            const streaming = !message.settled;
            const anyRunning = message.liveTools?.some((tool) => tool.status === "running") ?? false;

            // Assistant reasoning trace: expanded while the turn runs
            // (thinking text streams in + tool calls), collapsed after settle.
            const showTracePanel = message.role === "assistant"
              && ((message.trace && message.trace.length > 0) || tools.length > 0);
            const traceLabel = tools.some((tool) => tool.status === "running" || tool.status === "awaiting_approval")
              ? "正在调用工具…"
              : streaming ? "DeepSeek 思考中…" : "思考过程与工具调用";
            const waitingForAnswer = message.role === "assistant" && message.pending && !message.answerTrace;

            return (
              <div key={message.id} data-msg-id={message.id} className={`dsh-message dsh-message--${message.role}`}>
                {showTracePanel ? (
                  <details className={`dsh-trace${streaming ? " dsh-trace--open" : ""}`} open={streaming}>
                    <summary>
                      {streaming || anyRunning ? <span className="dsh-spinner dsh-spinner--inline" /> : null}
                      {traceLabel}
                    </summary>
                    <div className="dsh-trace__body">
                      {message.trace ? <div className="dsh-trace__reasoning">{message.trace}</div> : null}
                      <div className="dsh-message__tools">
                        {tools.map((call, index) => <ToolCallCard key={call.callId || index} call={call} />)}
                      </div>
                    </div>
                  </details>
                ) : null}

                {message.role === "assistant" ? (
                  waitingForAnswer ? (
                    <div className="dsh-thinking">
                      <span className="dsh-spinner dsh-spinner--inline" />
                      <span>{tools.length > 0 ? "正在调用工具" : "DeepSeek 思考中"}</span>
                    </div>
                  ) : (
                    <div className="dsh-message__bubble">
                      {message.pending
                        ? <Markdown raw>{message.answerTrace || ""}</Markdown>
                        : <Markdown>{message.text}</Markdown>}
                    </div>
                  )
                ) : (
                  <div className="dsh-message__bubble">{message.text}</div>
                )}

                {message.error ? <div className="dsh-error dsh-error--inline">{message.error}</div> : null}
              </div>
            );
          })}
        </div>

          {error && !messages.some((message) => message.error) ? <div className="dsh-error">{error}</div> : null}
        </main>

        {messages.length > 0 ? (
          <footer className="dsh-composer">
            <div className="dsh-composer-inner">{composerBody}</div>
          </footer>
        ) : null}
      </div>
    </div>
  );
}
