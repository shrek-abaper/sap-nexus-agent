import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync
} from "node:fs";
import path from "node:path";
import type { DurableConversationStore, SessionState } from "./types";

export class JsonlConversationStore implements DurableConversationStore {
  private readonly sessionsDir: string;

  constructor(private readonly dataDir: string) {
    this.sessionsDir = path.join(dataDir, "sessions");
    mkdirSync(this.sessionsDir, { recursive: true });
  }

  private file(conversationId: string): string {
    return path.join(this.sessionsDir, `${conversationId}.json`);
  }

  async save(conversationId: string, state: SessionState): Promise<void> {
    const target = this.file(conversationId);
    const tmp = `${target}.tmp`;
    writeFileSync(tmp, JSON.stringify(state), "utf8");
    renameSync(tmp, target);
  }

  async load(conversationId: string, principalId?: string): Promise<SessionState | null> {
    const file = this.file(conversationId);
    if (!existsSync(file)) return null;
    const state = JSON.parse(readFileSync(file, "utf8")) as SessionState;
    if (!state.principalId) {
      state.principalId = "local-user-0001";
    }
    if (principalId && state.principalId !== principalId) {
      return null;
    }
    return state;
  }

  async clear(conversationId: string): Promise<void> {
    const file = this.file(conversationId);
    if (existsSync(file)) {
      unlinkSync(file);
    }
  }

  async clearAll(): Promise<void> {
    if (!existsSync(this.sessionsDir)) return;
    for (const entry of readdirSync(this.sessionsDir)) {
      if (entry.endsWith(".json")) {
        unlinkSync(path.join(this.sessionsDir, entry));
      }
    }
  }
}
