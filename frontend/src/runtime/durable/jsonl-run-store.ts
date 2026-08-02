import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync,
  writeSync
} from "node:fs";
import path from "node:path";
import type { AgentRunEvent, AgentRunState } from "../run-event-schema";
import type {
  AgentRunRecord,
  ApprovalDecision,
  DurableRunStore,
  RunJsonlLine,
  WorkbenchOutcome
} from "./types";

export class JsonlRunStore implements DurableRunStore {
  private readonly runsDir: string;

  constructor(private readonly dataDir: string) {
    this.runsDir = path.join(dataDir, "runs");
    mkdirSync(this.runsDir, { recursive: true });
  }

  private runFile(runId: string): string {
    return path.join(this.runsDir, `${runId}.jsonl`);
  }

  // append + fsync per line (checkpoint decision A: every event is durable)
  private appendLine(runId: string, line: RunJsonlLine): void {
    const fd = openSync(this.runFile(runId), "a");
    try {
      writeSync(fd, JSON.stringify(line) + "\n", null, "utf8");
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
  }

  async save(runId: string, record: AgentRunRecord): Promise<void> {
    const file = this.runFile(runId);
    const lines: string[] = [JSON.stringify({ kind: "run_meta", runId, query: record.query } as RunJsonlLine)];
    for (const event of record.events) {
      lines.push(JSON.stringify({ kind: "event", ...event } as RunJsonlLine));
    }
    if (record.pendingOutcome) {
      lines.push(JSON.stringify({ kind: "pending_outcome", value: record.pendingOutcome } as RunJsonlLine));
    }
    if (record.decision) {
      lines.push(JSON.stringify({ kind: "decision", value: record.decision } as RunJsonlLine));
    }
    const content = lines.map((l) => l + "\n").join("");
    const tmp = `${file}.tmp`;
    writeFileSync(tmp, content, "utf8");
    const fd = openSync(tmp, "r");
    fsyncSync(fd);
    closeSync(fd);
    renameSync(tmp, file);
  }

  async load(runId: string): Promise<AgentRunRecord | null> {
    const file = this.runFile(runId);
    if (!existsSync(file)) return null;
    return this.replay(file);
  }

  private replay(file: string): AgentRunRecord {
    const content = readFileSync(file, "utf8");
    let query = "";
    const events: AgentRunEvent[] = [];
    let pendingOutcome: WorkbenchOutcome | undefined;
    let decision: ApprovalDecision | undefined;
    for (const raw of content.split("\n")) {
      if (!raw.trim()) continue;
      const line = JSON.parse(raw) as RunJsonlLine;
      switch (line.kind) {
        case "run_meta":
          query = line.query;
          break;
        case "event": {
          const { kind: _kind, ...event } = line;
          events.push(event as AgentRunEvent);
          break;
        }
        case "pending_outcome":
          pendingOutcome = line.value;
          break;
        case "decision":
          decision = line.value;
          break;
        case "checkpoint_ref":
          // consumed by loadCheckpointRef (Task 7); ignored here.
          break;
      }
    }
    events.sort((a, b) => a.sequence - b.sequence);
    const record: AgentRunRecord = { runId: path.basename(file, ".jsonl"), query, events };
    if (pendingOutcome) record.pendingOutcome = pendingOutcome;
    if (decision) record.decision = decision;
    return record;
  }

  async appendEvent(runId: string, event: AgentRunEvent): Promise<void> {
    this.appendLine(runId, { kind: "event", ...event });
  }

  async appendPendingOutcome(runId: string, outcome: WorkbenchOutcome): Promise<void> {
    this.appendLine(runId, { kind: "pending_outcome", value: outcome });
  }

  async appendDecision(runId: string, decision: ApprovalDecision): Promise<void> {
    this.appendLine(runId, { kind: "decision", value: decision });
  }

  async list(filter?: { state?: AgentRunState }): Promise<AgentRunRecord[]> {
    if (!existsSync(this.runsDir)) return [];
    const records: AgentRunRecord[] = [];
    for (const entry of readdirSync(this.runsDir)) {
      if (!entry.endsWith(".jsonl")) continue;
      const record = this.replay(path.join(this.runsDir, entry));
      const lastState = record.events[record.events.length - 1]?.state;
      if (!filter?.state || lastState === filter.state) {
        records.push(record);
      }
    }
    return records;
  }

  async clearAll(): Promise<void> {
    if (!existsSync(this.runsDir)) return;
    for (const entry of readdirSync(this.runsDir)) {
      if (entry.endsWith(".jsonl")) {
        unlinkSync(path.join(this.runsDir, entry));
      }
    }
  }
}
