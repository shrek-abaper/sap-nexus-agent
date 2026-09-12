"use client";

import { useRef, useState } from "react";
import { createConversationId } from "../agent-console/conversation-id";
import { ToolCallCard } from "./ToolCallCard";
import type { ChatMessage, DshTurnResponse } from "./types";

const SUGGESTIONS = [
  "DEMOA1 在 1000 工厂够不够用、在途多少？",
  "查客户 1000 的销售订单",
  "供应商 DEMOV1 的应付未清项，公司代码 1000",
];

export function DshChat() {
  const [conversationId] = useState(() => createConversationId());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const busyRef = useRef(false);
  const [busy, setBusy] = useState(false);

  async function send(content: string) {
    const trimmed = content.trim();
    if (!trimmed || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setText("");
    setMessages((previous) => [
      ...previous,
      { id: `u-${Date.now()}`, role: "user", text: trimmed },
      { id: `a-${Date.now()}`, role: "assistant", text: "", pending: true },
    ]);

    try {
      const response = await fetch(`/api/dsh/conversations/${encodeURIComponent(conversationId)}/messages`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: trimmed }),
      });
      const body = await response.json().catch(() => null) as
        | (DshTurnResponse & { errorType?: string; message?: string })
        | null;
      if (!response.ok || !body) {
        throw new Error(body?.message ?? body?.errorType ?? `HTTP ${response.status}`);
      }
      setMessages((previous) =>
        previous.map((message) =>
          message.pending
            ? {
                id: message.id,
                role: "assistant",
                text: body.output || "(无文本输出)",
                toolCalls: body.toolCalls,
              }
            : message,
        ),
      );
    } catch (sendError) {
      setMessages((previous) => previous.filter((message) => !message.pending));
      setError(sendError instanceof Error ? sendError.message : String(sendError));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="dsh-shell">
      <header className="dsh-header">
        <div className="dsh-header__title">SAP Nexus · DeepSeek Harness</div>
        <div className="dsh-header__sub">唯一对话运行时 · 语义工具经服务端治理执行</div>
      </header>

      <main className="dsh-main">
        {messages.length === 0 ? (
          <div className="dsh-empty">
            <p>用自然语言查询 SAP 业务事实，或发起补货申请（需人工审批）。</p>
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
          {messages.map((message) => (
            <div key={message.id} className={`dsh-message dsh-message--${message.role}`}>
              <div className="dsh-message__bubble">
                {message.pending ? <span className="dsh-typing">DeepSeek 思考中…</span> : message.text}
              </div>
              {message.toolCalls?.length ? (
                <div className="dsh-message__tools">
                  {message.toolCalls.map((call) => <ToolCallCard key={call.callId} call={call} />)}
                </div>
              ) : null}
            </div>
          ))}
        </div>

        {error ? <div className="dsh-error">{error}</div> : null}
      </main>

      <footer className="dsh-composer">
        <textarea
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
          rows={2}
        />
        <button type="button" className="dsh-send" disabled={busy || !text.trim()} onClick={() => send(text)}>
          发送
        </button>
      </footer>
    </div>
  );
}
