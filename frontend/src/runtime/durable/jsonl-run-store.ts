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
  CheckpointRef,
  DurableRunStore,
  LeaseOutcome,
  RunJsonlLine,
  WorkbenchOutcome
} from "./types";

export class JsonlRunStore implements DurableRunStore {
  private readonly runsDir: string;
  private readonly leasesDir: string;
  private readonly idempotencyDir: string;

  constructor(
    private readonly dataDir: string,
    private readonly workerId: string = `worker-${process.pid}`,
    private readonly defaultTtlMs: number = 60_000
  ) {
    this.runsDir = path.join(dataDir, "runs");
    this.leasesDir = path.join(dataDir, "leases");
    this.idempotencyDir = path.join(dataDir, "idempotency");
    mkdirSync(this.runsDir, { recursive: true });
    mkdirSync(this.leasesDir, { recursive: true });
    mkdirSync(this.idempotencyDir, { recursive: true });
  }

  private runFile(runId: string): string {
    return path.join(this.runsDir, `${runId}.jsonl`);
  }

  // --- lease persistence (leases/<runId>.json, tmp+rename atomic) ---

  private leaseFile(runId: string): string {
    return path.join(this.leasesDir, `${runId}.json`);
  }

  private writeLease(runId: string, workerId: string, ttlMs: number): void {
    const file = this.leaseFile(runId);
    const tmp = `${file}.tmp`;
    writeFileSync(tmp, JSON.stringify({ workerId, expiresAt: Date.now() + ttlMs }), "utf8");
    renameSync(tmp, file);
  }

  private readLease(runId: string): { workerId: string; expiresAt: number } | null {
    const file = this.leaseFile(runId);
    if (!existsSync(file)) return null;
    return JSON.parse(readFileSync(file, "utf8"));
  }

  async loadLeaseExpiry(runId: string): Promise<number | null> {
    return this.readLease(runId)?.expiresAt ?? null;
  }

  async claim(runId: string, workerId: string, ttlMs: number): Promise<LeaseOutcome> {
    const existing = this.readLease(runId);
    const now = Date.now();
    if (existing && existing.expiresAt > now && existing.workerId !== workerId) {
      return { status: "rejected", holder: existing.workerId, expiresAt: new Date(existing.expiresAt).toISOString() };
    }
    if (existing && existing.expiresAt <= now && existing.workerId !== workerId) {
      this.writeLease(runId, workerId, ttlMs);
      return { status: "force-claimed", previousHolder: existing.workerId };
    }
    this.writeLease(runId, workerId, ttlMs);
    return { status: "claimed" };
  }

  async release(runId: string, workerId: string): Promise<void> {
    const existing = this.readLease(runId);
    if (existing && existing.workerId === workerId) {
      unlinkSync(this.leaseFile(runId));
    }
  }

  async renew(runId: string, workerId: string, ttlMs: number): Promise<void> {
    const existing = this.readLease(runId);
    if (existing && existing.workerId === workerId) {
      this.writeLease(runId, workerId, ttlMs);
    }
    // no-op if lease absent or held by another worker
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
    const lines: string[] = [JSON.stringify({ kind: "run_meta", runId, query: record.query, principalId: record.principalId } as RunJsonlLine)];
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
    let principalId: string | undefined;
    const events: AgentRunEvent[] = [];
    let pendingOutcome: WorkbenchOutcome | undefined;
    let decision: ApprovalDecision | undefined;
    for (const raw of content.split("\n")) {
      if (!raw.trim()) continue;
      let line: RunJsonlLine;
      try {
        line = JSON.parse(raw) as RunJsonlLine;
      } catch {
        // corrupt line: skip (fail-closed, consistent with loadCheckpointRef)
        continue;
      }
      switch (line.kind) {
        case "run_meta":
          query = line.query;
          principalId = line.principalId;
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
    const record: AgentRunRecord = { runId: path.basename(file, ".jsonl"), query, events, principalId: principalId ?? "local-user-0001" };
    if (pendingOutcome) record.pendingOutcome = pendingOutcome;
    if (decision) record.decision = decision;
    return record;
  }

  async appendEvent(runId: string, event: AgentRunEvent): Promise<void> {
    this.appendLine(runId, { kind: "event", ...event });
    await this.renew(runId, this.workerId, this.defaultTtlMs);
  }

  async appendPendingOutcome(runId: string, outcome: WorkbenchOutcome): Promise<void> {
    this.appendLine(runId, { kind: "pending_outcome", value: outcome });
  }

  async appendDecision(runId: string, decision: ApprovalDecision): Promise<void> {
    this.appendLine(runId, { kind: "decision", value: decision });
  }

  async appendCheckpointRef(runId: string, ref: CheckpointRef): Promise<void> {
    this.appendLine(runId, { kind: "checkpoint_ref", value: ref });
  }

  async loadCheckpointRef(runId: string): Promise<CheckpointRef | null> {
    const file = this.runFile(runId);
    if (!existsSync(file)) return null;
    const content = readFileSync(file, "utf8");
    let latest: CheckpointRef | null = null;
    for (const raw of content.split("\n")) {
      if (!raw.trim()) continue;
      try {
        const line = JSON.parse(raw) as RunJsonlLine;
        if (line.kind === "checkpoint_ref") {
          latest = line.value;
        }
      } catch {
        // corrupt line: skip (fail-closed at store layer; caller decides)
      }
    }
    return latest;
  }

  // --- idempotency persistence (idempotency/<safekey>.json, tmp+rename atomic) ---

  private idempotencyFile(key: string): string {
    const safe = key.replace(/[^a-zA-Z0-9_-]/g, "_");
    return path.join(this.idempotencyDir, `${safe}.json`);
  }

  async markExecuted(key: string, result: WorkbenchOutcome): Promise<void> {
    const file = this.idempotencyFile(key);
    const tmp = `${file}.tmp`;
    writeFileSync(tmp, JSON.stringify({ result, executedAt: new Date().toISOString() }), "utf8");
    renameSync(tmp, file);
  }

  async lookupExecuted(key: string): Promise<WorkbenchOutcome | null> {
    const file = this.idempotencyFile(key);
    if (!existsSync(file)) return null;
    const record = JSON.parse(readFileSync(file, "utf8")) as { result: WorkbenchOutcome; executedAt: string };
    return record.result;
  }

  async list(filter?: { state?: AgentRunState; principalId?: string }): Promise<AgentRunRecord[]> {
    if (!existsSync(this.runsDir)) return [];
    const records: AgentRunRecord[] = [];
    for (const entry of readdirSync(this.runsDir)) {
      if (!entry.endsWith(".jsonl")) continue;
      const record = this.replay(path.join(this.runsDir, entry));
      const lastState = record.events[record.events.length - 1]?.state;
      const stateMatch = !filter?.state || lastState === filter.state;
      const principalMatch = !filter?.principalId || record.principalId === filter.principalId;
      if (stateMatch && principalMatch) {
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
