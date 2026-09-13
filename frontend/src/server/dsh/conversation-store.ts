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
type RecordLine = HeaderRecord | MessageRecord;

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
  }): Promise<void> {
    const records = readRecords();
    const hasHeader = records.some((r) => r.kind === "conversation" && r.id === input.conversationId);
    const now = Date.now();
    const baseId = input.conversationId;

    if (!hasHeader) {
      await append({
        kind: "conversation",
        id: baseId,
        title: titleFrom(input.userText),
        createdAt: now,
      });
    }

    await append({
      kind: "message",
      conversationId: baseId,
      id: `u-${now}`,
      role: "user",
      text: input.userText,
      ts: now,
    });
    await append({
      kind: "message",
      conversationId: baseId,
      id: `a-${now}`,
      role: "assistant",
      text: input.assistantText,
      ...(input.assistantReasoning ? { reasoning: input.assistantReasoning } : {}),
      ...(input.assistantToolCalls ? { toolCalls: input.assistantToolCalls } : {}),
      ...(input.assistantError ? { error: input.assistantError } : {}),
      ts: now + 1,
    });
  },

  list(): StoredConversationSummary[] {
    const records = readRecords();
    const byId = new Map<string, StoredConversationSummary>();
    for (const record of records) {
      if (record.kind === "conversation") {
        byId.set(record.id, {
          id: record.id,
          title: record.title,
          createdAt: record.createdAt,
          updatedAt: record.createdAt,
          messageCount: 0,
        });
      } else {
        const summary = byId.get(record.conversationId) ?? {
          id: record.conversationId,
          title: titleFrom(record.role === "user" ? record.text : "新会话"),
          createdAt: record.ts,
          updatedAt: record.ts,
          messageCount: 0,
        };
        summary.messageCount += 1;
        summary.updatedAt = Math.max(summary.updatedAt, record.ts);
        byId.set(record.conversationId, summary);
      }
    }
    return [...byId.values()].sort((a, b) => b.updatedAt - a.updatedAt);
  },

  get(id: string): StoredConversation | null {
    const records = readRecords();
    const header = records.find((r) => r.kind === "conversation" && r.id === id) as HeaderRecord | undefined;
    if (!header) return null;
    const messages: StoredMessage[] = records
      .filter((r): r is MessageRecord => r.kind === "message" && r.conversationId === id)
      .map(({ kind: _kind, conversationId: _cid, ...message }) => message)
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

  async remove(id: string): Promise<boolean> {
    const file = dataFile();
    const before = readRecords();
    const kept = before.filter(
      (record) =>
        !(record.kind === "conversation" && record.id === id)
        && !(record.kind === "message" && record.conversationId === id),
    );
    if (kept.length === before.length) return false;
    writeChain = writeChain.then(() => {
      writeFileSync(file, kept.map((record) => JSON.stringify(record)).join("\n") + (kept.length ? "\n" : ""));
    });
    await writeChain;
    return true;
  },
};
