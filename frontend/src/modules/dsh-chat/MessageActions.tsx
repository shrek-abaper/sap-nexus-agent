"use client";

import { useState } from "react";
import type { ChatMessage } from "./types";

// DSH-native message action chrome (ui-conversation MessageIconActions
// analogue): icon buttons stay visible when mounted; the clock/duration
// label is hover-revealed by the surrounding [data-hover-root] container.

type IconProps = { size?: number };

function IconBase({ size = 15, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

function CopyIcon() {
  return (
    <IconBase>
      <rect width="14" height="14" x="8" y="8" rx="2" />
      <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
    </IconBase>
  );
}

function CheckIcon() {
  return (
    <IconBase>
      <path d="M20 6 9 17l-5-5" />
    </IconBase>
  );
}

function LikeIcon({ active }: { active?: boolean }) {
  return (
    <IconBase>
      <path
        d="M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"
        fill={active ? "currentColor" : "none"}
      />
    </IconBase>
  );
}

function DislikeIcon({ active }: { active?: boolean }) {
  return (
    <IconBase>
      <path
        d="M17 14V2M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"
        fill={active ? "currentColor" : "none"}
      />
    </IconBase>
  );
}

function BranchIcon() {
  return (
    <IconBase>
      <path d="M6 3v12" />
      <circle cx="18" cy="6" r="3" />
      <circle cx="6" cy="18" r="3" />
      <path d="M18 9a9 9 0 0 1-9 9" />
    </IconBase>
  );
}

function formatClock(ts: number): string {
  const date = new Date(ts);
  const now = new Date();
  const time = date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  return `${date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })} ${time}`;
}

function formatRunMs(runMs: number): string {
  const seconds = runMs / 1000;
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
}

async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="msg-actions__btn"
      aria-label={copied ? "已复制" : label}
      title={copied ? "已复制" : label}
      onClick={async () => {
        if (await writeClipboard(text)) {
          setCopied(true);
          setTimeout(() => setCopied(false), 1000);
        }
      }}
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
    </button>
  );
}

export type MessageActionsProps = {
  message: ChatMessage;
  onRate: (rating: "up" | "down" | null) => void;
  onSaveNote: (note: string) => void;
  onBranch: (() => void) | null;
  branchError?: string | null;
};

/** Turn-tail row under a settled assistant message. */
export function AssistantMessageActions({ message, onRate, onSaveNote, onBranch, branchError }: MessageActionsProps) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [draft, setDraft] = useState(message.feedback?.note ?? "");
  const rating = message.feedback?.rating;

  return (
    <div className="msg-actions" data-hover-root>
      <CopyButton text={message.text} label="复制 markdown" />
      <button
        type="button"
        className={`msg-actions__btn${rating === "up" ? " is-active" : ""}`}
        aria-label="赞"
        title="赞"
        onClick={() => onRate(rating === "up" ? null : "up")}
      >
        <LikeIcon active={rating === "up"} />
      </button>
      <button
        type="button"
        className={`msg-actions__btn${rating === "down" ? " is-active" : ""}`}
        aria-label="踩"
        title="踩"
        onClick={() => onRate(rating === "down" ? null : "down")}
      >
        <DislikeIcon active={rating === "down"} />
      </button>
      {rating ? (
        <button
          type="button"
          className="msg-actions__note-toggle"
          onClick={() => {
            setDraft(message.feedback?.note ?? "");
            setNoteOpen((open) => !open);
          }}
        >
          {message.feedback?.note ? "备注 ✎" : "备注"}
        </button>
      ) : null}
      {onBranch ? (
        <button
          type="button"
          className="msg-actions__btn"
          aria-label="从此处分叉"
          title="从此轮分叉出新会话"
          onClick={onBranch}
        >
          <BranchIcon />
        </button>
      ) : null}
      {message.ts ? (
        <span className="msg-actions__meta">
          {formatClock(message.ts)}
          {message.runMs ? ` · 耗时 ${formatRunMs(message.runMs)}` : ""}
        </span>
      ) : null}
      {branchError ? <span className="msg-actions__error">{branchError}</span> : null}
      {noteOpen ? (
        <div className="msg-actions__note-editor">
          <textarea
            value={draft}
            placeholder="补充备注（可选），保存空备注等于清除备注"
            rows={2}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="msg-actions__note-actions">
            <button
              type="button"
              className="sn-btn sn-btn--primary"
              onClick={() => {
                onSaveNote(draft.trim());
                setNoteOpen(false);
              }}
            >
              保存
            </button>
            <button type="button" className="sn-btn sn-btn--ghost" onClick={() => setNoteOpen(false)}>
              取消
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** Hover-revealed copy + clock row under a user bubble. */
export function UserMessageActions({ message }: { message: ChatMessage }) {
  return (
    <div className="msg-actions msg-actions--user">
      <CopyButton text={message.text} label="复制" />
      {message.ts ? <span className="msg-actions__meta">{formatClock(message.ts)}</span> : null}
    </div>
  );
}
