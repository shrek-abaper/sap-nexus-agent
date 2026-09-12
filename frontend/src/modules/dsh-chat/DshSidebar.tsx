"use client";

import type { ConversationSummary } from "./types";

type DshSidebarProps = {
  conversations: ConversationSummary[];
  currentId: string;
  loading: boolean;
  onNewConversation: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onCollapse: () => void;
};

function formatTime(ts: number): string {
  const date = new Date(ts);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

// Lucide "panel-left" icon used by the reference client.
function PanelLeftIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect width="18" height="18" x="3" y="3" rx="2" />
      <path d="M9 3v18" />
    </svg>
  );
}

export function DshSidebar({
  conversations,
  currentId,
  loading,
  onNewConversation,
  onSelect,
  onDelete,
  onCollapse,
}: DshSidebarProps) {
  return (
    <aside className="dsh-sidebar">
      {/* Header: brand left, collapse toggle right (60px row). */}
      <div className="dsh-sidebar__brand">
        <div className="dsh-sidebar__brand-left">
          <div className="dsh-sidebar__logo" aria-hidden>◆</div>
          <div className="dsh-sidebar__name">SAP Nexus</div>
        </div>
        <button
          type="button"
          className="dsh-collapse"
          onClick={onCollapse}
          aria-label="折叠侧栏"
          title="折叠侧栏"
        >
          <PanelLeftIcon />
        </button>
      </div>

      <button type="button" className="dsh-newchat" onClick={onNewConversation}>
        <span className="dsh-newchat__plus" aria-hidden>＋</span>
        新建会话
      </button>

      <div className="dsh-sidebar__list">
        <div className="dsh-sidebar__label">历史会话</div>
        {loading ? <div className="dsh-sidebar__empty">加载中…</div> : null}
        {!loading && conversations.length === 0 ? (
          <div className="dsh-sidebar__empty">暂无历史会话</div>
        ) : null}
        {conversations.map((conversation) => (
          <div
            key={conversation.id}
            className={`dsh-history${conversation.id === currentId ? " is-active" : ""}`}
          >
            <button
              type="button"
              className="dsh-history__open"
              onClick={() => onSelect(conversation.id)}
              title={conversation.title}
            >
              <span className="dsh-history__title">{conversation.title || "新会话"}</span>
              <span className="dsh-history__meta">{formatTime(conversation.updatedAt)}</span>
            </button>
            <button
              type="button"
              className="dsh-history__delete"
              onClick={(event) => {
                event.stopPropagation();
                onDelete(conversation.id);
              }}
              aria-label={`删除会话 ${conversation.title}`}
              title="删除会话"
            >
              ✕
            </button>
          </div>
        ))}
      </div>

      <div className="dsh-sidebar__footer">
        <span className="dsh-sidebar__dot" aria-hidden />
        <span>DeepSeek Harness 运行时</span>
      </div>
    </aside>
  );
}
