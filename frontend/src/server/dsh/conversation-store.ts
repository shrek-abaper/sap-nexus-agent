import "server-only";

import { mkdirSync, appendFileSync, readFileSync, existsSync, writeFileSync } from "node:fs";
import path from "node:path";

// Server-side persistence for dsh chat history. One append-only JSONL file:
// a "conversation" header is written the first time a turn is stored, then
// one "message" record per user/assistant turn. This backs the sidebar list
// and history view independently of the in-memory dsh agent sessions.
//
// Note: the dsh agent's own working memory is still in-memory; after a server
// restart, stored messages remain readable but continuing a conversation
// starts a fresh agent session (durable agent memory is a separate upgrade).

export type StoredToolCall = Record<string, unknown>;

export type StoredMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** Full pre-tool reasoning trace, retained so history replays the chain. */
  reasoning?: string;
  toolCalls?: StoredToolCall[];
  error?: string;
  ts: number;
  /** Latest feedback record for this message, merged at read time. */
  feedback?: StoredFeedback;
};

export type StoredConversationSummary = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
};

export type StoredConversation = StoredConversationSummary & {
  messages: StoredMessage[];
};

export type MessageRating = "up" | "down";

export type StoredFeedback = {
  rating: MessageRating;
  note?: string;
  ts: number;
};

type HeaderRecord = {
  kind: "conversation";
  id: string;
  title: string;
  createdAt: number;
};
type MessageRecord = StoredMessage & {
  kind: "message";
  conversationId: string;
};
// Feedback is append-only like messages: the latest record per
// (conversationId, messageId) wins; rating null with no note is a tombstone.
type FeedbackRecord = {
  kind: "feedback";
  conversationId: string;
  messageId: string;
  rating: MessageRating | null;
  note?: string;
  ts: number;
};
type RecordLine = HeaderRecord | MessageRecord | FeedbackRecord;

const TITLE_MAX = 24;

function dataDir(): string {
  return process.env.WORKBENCH_DATA_DIR
    ? path.join(process.env.WORKBENCH_DATA_DIR, "dsh")
    : path.join(process.cwd(), ".workbench-data", "dsh");
}

function dataFile(): string {
  const dir = dataDir();
  mkdirSync(dir, { recursive: true });
  return path.join(dir, "conversations.jsonl");
}

// Serialize concurrent appends within the process.
let writeChain: Promise<void> = Promise.resolve();

function readRecords(): RecordLine[] {
  const file = dataFile();
  if (!existsSync(file)) return [];
  const lines = readFileSync(file, "utf8").split("\n");
  const records: RecordLine[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      records.push(JSON.parse(trimmed) as RecordLine);
    } catch {
      // Skip a corrupted trailing line rather than failing the whole history.
    }
  }
  return records;
}

function append(record: RecordLine): Promise<void> {
  writeChain = writeChain.then(() => {
    appendFileSync(dataFile(), `${JSON.stringify(record)}\n`);
  });
  return writeChain;
}

function titleFrom(text: string): string {
  const oneLine = text.replace(/\s+/g, " ").trim();
  return oneLine.length > TITLE_MAX ? `${oneLine.slice(0, TITLE_MAX)}…` : oneLine;
}

export const dshConversationStore = {
  async addTurn(input: {
    conversationId: string;
    userText: string;
    assistantText: string;
    assistantReasoning?: string;
    assistantToolCalls?: StoredToolCall[];
    assistantError?: string;
  }): Promise<{ userMessageId: string; assistantMessageId: string }> {
    const records = readRecords();
    const hasHeader = records.some((r) => r.kind === "conversation" && r.id === input.conversationId);
    // Message ts must be strictly increasing: two turns landing in the same
    // millisecond would otherwise tie on ts, and the ts-sorted read path
    // would interleave them (user2 replayed before assistant1) and collide
    // on the u-/a-<ts> message ids.
    let lastTs = 0;
    for (const record of records) {
      if (record.kind === "message" || record.kind === "feedback") lastTs = Math.max(lastTs, record.ts);
    }
    const userTs = Math.max(Date.now(), lastTs + 1);
    const assistantTs = userTs + 1;
    const baseId = input.conversationId;

    if (!hasHeader) {
      await append({
        kind: "conversation",
        id: baseId,
        title: titleFrom(input.userText),
        createdAt: userTs,
      });
    }

    await append({
      kind: "message",
      conversationId: baseId,
      id: `u-${userTs}`,
      role: "user",
      text: input.userText,
      ts: userTs,
    });
    await append({
      kind: "message",
      conversationId: baseId,
      id: `a-${assistantTs}`,
      role: "assistant",
      text: input.assistantText,
      ...(input.assistantReasoning ? { reasoning: input.assistantReasoning } : {}),
      ...(input.assistantToolCalls ? { toolCalls: input.assistantToolCalls } : {}),
      ...(input.assistantError ? { error: input.assistantError } : {}),
      ts: assistantTs,
    });
    return { userMessageId: `u-${userTs}`, assistantMessageId: `a-${assistantTs}` };
  },

  list(): StoredConversationSummary[] {
    const records = readRecords();
    type IndexedSummary = StoredConversationSummary & { firstSeenIndex: number };
    const byId = new Map<string, IndexedSummary>();
    records.forEach((record, index) => {
      if (record.kind === "conversation") {
        byId.set(record.id, {
          id: record.id,
          title: record.title,
          createdAt: record.createdAt,
          updatedAt: record.createdAt,
          messageCount: 0,
          firstSeenIndex: index,
        });
      } else if (record.kind === "feedback") {
        // Feedback records never affect summaries or message counts.
        return;
      } else {
        const existing = byId.get(record.conversationId);
        const summary: IndexedSummary = existing ?? {
          id: record.conversationId,
          title: titleFrom(record.role === "user" ? record.text : "新会话"),
          createdAt: record.ts,
          updatedAt: record.ts,
          messageCount: 0,
          firstSeenIndex: index,
        };
        summary.messageCount += 1;
        summary.updatedAt = Math.max(summary.updatedAt, record.ts);
        byId.set(record.conversationId, summary);
      }
    });
    // Updated time first; the append-order index breaks same-millisecond ties
    // (the store writes ms timestamps and turns may land in one millisecond
    // under parallel test load).
    return [...byId.values()]
      .sort((a, b) => b.updatedAt - a.updatedAt || b.firstSeenIndex - a.firstSeenIndex)
      .map(({ firstSeenIndex: _ignored, ...summary }) => summary);
  },

  get(id: string): StoredConversation | null {
    const records = readRecords();
    const header = records.find((r) => r.kind === "conversation" && r.id === id) as HeaderRecord | undefined;
    if (!header) return null;
    // Latest feedback record per message wins; tombstones (rating null and
    // no note) hide the entry entirely.
    const feedbackByMessage = new Map<string, FeedbackRecord>();
    for (const record of records) {
      if (record.kind === "feedback" && record.conversationId === id) {
        feedbackByMessage.set(record.messageId, record);
      }
    }
    const messages: StoredMessage[] = records
      .filter((r): r is MessageRecord => r.kind === "message" && r.conversationId === id)
      .map(({ kind: _kind, conversationId: _cid, ...message }) => {
        const feedback = feedbackByMessage.get(message.id);
        // Only an active rating is surfaced; a note persists in storage and
        // reappears when the user rates again (UI never produces note-only).
        if (feedback?.rating) {
          return {
            ...message,
            feedback: {
              rating: feedback.rating,
              ...(feedback.note ? { note: feedback.note } : {}),
              ts: feedback.ts,
            },
          };
        }
        return message;
      })
      .sort((a, b) => a.ts - b.ts);
    const updatedAt = messages.reduce((max, m) => Math.max(max, m.ts), header.createdAt);
    return {
      id,
      title: header.title,
      createdAt: header.createdAt,
      updatedAt,
      messageCount: messages.length,
      messages,
    };
  },

  // Upsert the latest feedback state for one message. `rating: null` with
  // no surviving note is a tombstone; omitting `note` keeps the prior note.
  async setFeedback(input: {
    conversationId: string;
    messageId: string;
    rating: MessageRating | null;
    note?: string;
  }): Promise<void> {
    const records = readRecords();
    let previous: FeedbackRecord | undefined;
    for (const record of records) {
      if (record.kind === "feedback"
        && record.conversationId === input.conversationId
        && record.messageId === input.messageId) {
        previous = record;
      }
    }
    const note = input.note !== undefined ? input.note : previous?.note;
    await append({
      kind: "feedback",
      conversationId: input.conversationId,
      messageId: input.messageId,
      rating: input.rating,
      ...(note ? { note } : {}),
      ts: Date.now(),
    });
  },

  // Copy the parent conversation's message prefix (through throughMessageId,
  // inclusive) into a new conversation. Message ids are preserved; feedback
  // is not carried over. Returns the new conversation, or null when the
  // parent or the message is unknown.
  async forkConversation(input: {
    parentId: string;
    throughMessageId: string;
    newId: string;
  }): Promise<StoredConversation | null> {
    const parent = this.get(input.parentId);
    if (!parent) return null;
    const cutIndex = parent.messages.findIndex((message) => message.id === input.throughMessageId);
    if (cutIndex < 0) return null;
    const prefix = parent.messages.slice(0, cutIndex + 1).map(({ feedback: _f, ...message }) => message);
    const now = Date.now();
    await append({
      kind: "conversation",
      id: input.newId,
      title: titleFrom(`${parent.title} · 分叉`),
      createdAt: now,
    });
    for (const message of prefix) {
      await append({
        kind: "message",
        conversationId: input.newId,
        ...message,
      });
    }
    return this.get(input.newId);
  },

  async remove(id: string): Promise<boolean> {
    const file = dataFile();
    const before = readRecords();
    const kept = before.filter(
      (record) =>
        !(record.kind === "conversation" && record.id === id)
        && !(record.kind === "message" && record.conversationId === id)
        && !(record.kind === "feedback" && record.conversationId === id),
    );
    if (kept.length === before.length) return false;
    writeChain = writeChain.then(() => {
      writeFileSync(file, kept.map((record) => JSON.stringify(record)).join("\n") + (kept.length ? "\n" : ""));
    });
    await writeChain;
    return true;
  },
};
