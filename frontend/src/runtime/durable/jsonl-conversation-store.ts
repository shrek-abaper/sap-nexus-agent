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
} from "node:fs";
import path from "node:path";
import type {
  ConversationCasOutcome,
  ConversationStoreErrorCode,
  ConversationTurnLookup,
  DurableConversationStore,
  LastContext,
  LeaseOutcome,
  PendingInteraction,
  ReadContextFrame,
  SessionState,
  SessionStateV2,
  SlotBinding,
  Turn,
} from "./types";

const LEGACY_PRINCIPAL = "local-user-0001";
const conversationLocks = new Map<string, Promise<void>>();
type LoadedSessionStateV2 = SessionStateV2 & { readonly lastContext?: LastContext | null };

export class ConversationStoreError extends Error {
  constructor(
    readonly code: ConversationStoreErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "ConversationStoreError";
  }
}

export class JsonlConversationStore implements DurableConversationStore {
  private readonly sessionsDir: string;
  private readonly leasesDir: string;

  constructor(private readonly dataDir: string) {
    this.sessionsDir = path.join(dataDir, "sessions");
    this.leasesDir = path.join(dataDir, "conversation-leases");
    mkdirSync(this.sessionsDir, { recursive: true });
    mkdirSync(this.leasesDir, { recursive: true });
  }

  private file(conversationId: string): string {
    return path.join(this.sessionsDir, `${conversationId}.json`);
  }

  private leaseFile(conversationId: string): string {
    return path.join(this.leasesDir, `${conversationId}.json`);
  }

  private lockKey(conversationId: string): string {
    return path.resolve(this.file(conversationId));
  }

  // Retained only for pre-v2 concrete callers. Runtime code uses compareAndSwap.
  async save(conversationId: string, state: SessionState | SessionStateV2): Promise<void> {
    await withConversationLock(this.lockKey(conversationId), () => {
      const principalId = state.principalId ?? LEGACY_PRINCIPAL;
      if (existsSync(this.file(conversationId))) {
        this.loadUnlocked(conversationId, principalId);
      }
      const next = isSessionStateV2(state)
        ? validateSessionV2(state)
        : {
            ...migrateLegacySession(state, principalId),
            legacyLastContext: state.lastContext,
          };
      this.writeAtomically(this.file(conversationId), next);
    });
  }

  async load(
    conversationId: string,
    principalId: string = LEGACY_PRINCIPAL,
  ): Promise<LoadedSessionStateV2 | null> {
    return withConversationLock(this.lockKey(conversationId), () =>
      this.loadUnlocked(conversationId, principalId));
  }

  async claim(conversationId: string, workerId: string, ttlMs: number): Promise<LeaseOutcome> {
    return withConversationLock(this.lockKey(conversationId), () => {
      if (!workerId || !Number.isFinite(ttlMs) || ttlMs <= 0) {
        throw new ConversationStoreError(
          "CONVERSATION_LEASE_INVALID",
          "Conversation lease requires a worker id and positive TTL",
        );
      }
      const existing = this.readLease(conversationId);
      const now = Date.now();
      if (existing && existing.expiresAt > now && existing.workerId !== workerId) {
        return {
          status: "rejected",
          holder: existing.workerId,
          expiresAt: new Date(existing.expiresAt).toISOString(),
        };
      }
      if (existing && existing.expiresAt <= now && existing.workerId !== workerId) {
        this.writeLease(conversationId, workerId, ttlMs);
        return { status: "force-claimed", previousHolder: existing.workerId };
      }
      this.writeLease(conversationId, workerId, ttlMs);
      return { status: "claimed" };
    });
  }

  async compareAndSwap(
    conversationId: string,
    expectedVersion: number,
    next: SessionStateV2,
  ): Promise<ConversationCasOutcome> {
    return withConversationLock(this.lockKey(conversationId), () => {
      if (!Number.isSafeInteger(expectedVersion) || expectedVersion < 0) {
        throw new ConversationStoreError(
          "CONTEXT_INVALID_VERSION_TRANSITION",
          "expectedVersion must be a non-negative integer",
        );
      }
      const validatedNext = validateSessionV2(next);
      if (validatedNext.stateVersion !== expectedVersion + 1) {
        throw new ConversationStoreError(
          "CONTEXT_INVALID_VERSION_TRANSITION",
          `Expected next stateVersion ${expectedVersion + 1}, received ${validatedNext.stateVersion}`,
        );
      }

      const existing = this.loadUnlocked(conversationId, validatedNext.principalId);
      const actualVersion = existing?.stateVersion ?? 0;
      if (actualVersion !== expectedVersion) {
        return { status: "conflict", actualVersion };
      }

      this.writeAtomically(this.file(conversationId), validatedNext);
      return { status: "saved", stateVersion: validatedNext.stateVersion };
    });
  }

  async release(conversationId: string, workerId: string): Promise<void> {
    await withConversationLock(this.lockKey(conversationId), () => {
      const existing = this.readLease(conversationId);
      if (existing?.workerId === workerId) {
        unlinkSync(this.leaseFile(conversationId));
      }
    });
  }

  async lookupTurn(
    conversationId: string,
    principalId: string,
    turnId: string,
  ): Promise<ConversationTurnLookup | null> {
    const session = await this.load(conversationId, principalId);
    if (session?.lastAppliedTurnId !== turnId || !session.lastRunId) return null;
    return { runId: session.lastRunId };
  }

  async clear(conversationId: string): Promise<void> {
    await withConversationLock(this.lockKey(conversationId), () => {
      unlinkIfPresent(this.file(conversationId));
      unlinkIfPresent(this.leaseFile(conversationId));
    });
  }

  async clearAll(): Promise<void> {
    for (const entry of readdirSync(this.sessionsDir)) {
      if (entry.endsWith(".json")) unlinkSync(path.join(this.sessionsDir, entry));
    }
    for (const entry of readdirSync(this.leasesDir)) {
      if (entry.endsWith(".json")) unlinkSync(path.join(this.leasesDir, entry));
    }
  }

  private loadUnlocked(conversationId: string, principalId: string): SessionStateV2 | null {
    const file = this.file(conversationId);
    if (!existsSync(file)) return null;
    try {
      const payload = JSON.parse(readFileSync(file, "utf8")) as unknown;
      const session = isSessionStateV2(payload)
        ? validateSessionV2(payload)
        : migrateLegacySession(payload, principalId);
      if (session.principalId !== principalId) {
        throw new ConversationStoreError(
          "CONTEXT_PRINCIPAL_MISMATCH",
          "Conversation does not belong to the current principal",
        );
      }
      return session;
    } catch (error) {
      if (error instanceof ConversationStoreError) throw error;
      throw new ConversationStoreError(
        "CONTEXT_DESERIALIZATION_FAILED",
        `Conversation session could not be deserialized: ${errorMessage(error)}`,
      );
    }
  }

  private readLease(conversationId: string): { workerId: string; expiresAt: number } | null {
    const file = this.leaseFile(conversationId);
    if (!existsSync(file)) return null;
    try {
      const value = JSON.parse(readFileSync(file, "utf8")) as unknown;
      const record = requireRecord(value, "conversation lease");
      return {
        workerId: requireString(record.workerId, "conversation lease workerId"),
        expiresAt: requireNonNegativeInteger(record.expiresAt, "conversation lease expiresAt"),
      };
    } catch (error) {
      throw new ConversationStoreError(
        "CONVERSATION_LEASE_INVALID",
        `Conversation lease could not be read: ${errorMessage(error)}`,
      );
    }
  }

  private writeLease(conversationId: string, workerId: string, ttlMs: number): void {
    this.writeAtomically(this.leaseFile(conversationId), {
      workerId,
      expiresAt: Date.now() + ttlMs,
    });
  }

  private writeAtomically(file: string, value: unknown): void {
    const tmp = `${file}.${process.pid}.${crypto.randomUUID()}.tmp`;
    writeFileSync(tmp, JSON.stringify(value), "utf8");
    const fd = openSync(tmp, "r");
    try {
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
    renameSync(tmp, file);
  }
}

async function withConversationLock<T>(key: string, operation: () => T | Promise<T>): Promise<T> {
  const previous = conversationLocks.get(key) ?? Promise.resolve();
  let unlock!: () => void;
  const current = new Promise<void>((resolve) => { unlock = resolve; });
  const tail = previous.then(() => current);
  conversationLocks.set(key, tail);
  await previous;
  try {
    return await operation();
  } finally {
    unlock();
    if (conversationLocks.get(key) === tail) conversationLocks.delete(key);
  }
}

function migrateLegacySession(payload: unknown, principalId: string): SessionStateV2 {
  const legacy = requireRecord(payload, "legacy SessionState");
  const storedPrincipal = legacy.principalId === undefined
    ? LEGACY_PRINCIPAL
    : requireString(legacy.principalId, "legacy principalId");
  if (storedPrincipal !== principalId) {
    throw new ConversationStoreError(
      "CONTEXT_PRINCIPAL_MISMATCH",
      "Conversation does not belong to the current principal",
    );
  }
  const lastContext = legacy.lastContext === null || legacy.lastContext === undefined
    ? null
    : parseLastContext(legacy.lastContext);
  const migrated: SessionStateV2 = {
    schemaVersion: 2,
    stateVersion: 0,
    principalId: storedPrincipal,
    activeFrame: lastContext ? migrateLegacyFrame(lastContext) : null,
    recentFrames: [],
    pendingInteraction: null,
    history: parseTurns(legacy.history ?? []),
    lastAppliedTurnId: null,
    lastRunId: nullableString(legacy.lastRunId, "legacy lastRunId"),
  };
  // Keep old concrete-store readers compiling without serializing or trusting LastContext in v2.
  Object.defineProperty(migrated, "lastContext", { value: lastContext, enumerable: false });
  return migrated;
}

function migrateLegacyFrame(context: LastContext): ReadContextFrame {
  const sourceTurnId = "legacy-migration";
  const slots: Record<string, SlotBinding> = {};
  for (const [name, value] of Object.entries(context.parameters)) {
    slots[name] = {
      name,
      value,
      candidates: [],
      state: "RESOLVED",
      provenance: "INHERITED_LEGACY",
      sourceTurnId,
      sourceSpan: null,
      issues: ["legacy_context_requires_revalidation"],
    };
  }
  for (const name of context.missingParameters) {
    if (slots[name]) continue;
    slots[name] = {
      name,
      value: null,
      candidates: [],
      state: "CLEARED",
      provenance: "INHERITED_LEGACY",
      sourceTurnId,
      sourceSpan: null,
      issues: ["legacy_context_requires_revalidation"],
    };
  }
  return {
    frameId: `legacy-${context.capabilityId.replace(/[^A-Za-z0-9_.-]/g, "-")}`,
    capabilityId: context.capabilityId,
    slots,
    status: "STALE",
    createdTurnId: sourceTurnId,
    updatedTurnId: sourceTurnId,
    registrySnapshotId: "legacy-unknown",
    capabilityVersion: "legacy-unknown",
  };
}

function validateSessionV2(payload: unknown): SessionStateV2 {
  const raw = requireRecord(payload, "SessionStateV2");
  if (raw.schemaVersion !== 2) throw new Error("SessionStateV2.schemaVersion must be 2");
  const recentFrames = requireArray(raw.recentFrames, "SessionStateV2.recentFrames").map(parseFrame);
  if (recentFrames.length > 2) throw new Error("SessionStateV2.recentFrames must contain at most two frames");
  const legacyLastContext = raw.legacyLastContext === undefined
    ? undefined
    : raw.legacyLastContext === null ? null : parseLastContext(raw.legacyLastContext);
  const session: SessionStateV2 = {
    schemaVersion: 2,
    stateVersion: requireNonNegativeInteger(raw.stateVersion, "SessionStateV2.stateVersion"),
    principalId: requireString(raw.principalId, "SessionStateV2.principalId"),
    activeFrame: raw.activeFrame === null ? null : parseFrame(raw.activeFrame),
    recentFrames,
    pendingInteraction: raw.pendingInteraction === null ? null : parsePending(raw.pendingInteraction),
    history: parseTurns(raw.history),
    lastAppliedTurnId: nullableString(raw.lastAppliedTurnId, "SessionStateV2.lastAppliedTurnId"),
    lastRunId: nullableString(raw.lastRunId, "SessionStateV2.lastRunId"),
  };
  if (legacyLastContext !== undefined) {
    Object.defineProperty(session, "lastContext", { value: legacyLastContext, enumerable: false });
  }
  return session;
}

function parseFrame(payload: unknown): ReadContextFrame {
  const raw = requireRecord(payload, "ReadContextFrame");
  const status = requireEnum(raw.status, ["COLLECTING", "READY", "CONFLICTED", "STALE"] as const, "ReadContextFrame.status");
  const rawSlots = requireRecord(raw.slots, "ReadContextFrame.slots");
  const slots: Record<string, SlotBinding> = {};
  for (const [name, slot] of Object.entries(rawSlots)) {
    const parsed = parseSlot(slot);
    if (parsed.name !== name) throw new Error("ReadContextFrame slot key must match SlotBinding.name");
    slots[name] = parsed;
  }
  if (status === "READY" && Object.values(slots).some((slot) => slot.state !== "RESOLVED")) {
    throw new Error("READY frame requires all slots to be RESOLVED");
  }
  return {
    frameId: requireString(raw.frameId, "ReadContextFrame.frameId"),
    capabilityId: requireString(raw.capabilityId, "ReadContextFrame.capabilityId"),
    slots,
    status,
    createdTurnId: requireString(raw.createdTurnId, "ReadContextFrame.createdTurnId"),
    updatedTurnId: requireString(raw.updatedTurnId, "ReadContextFrame.updatedTurnId"),
    registrySnapshotId: requireString(raw.registrySnapshotId, "ReadContextFrame.registrySnapshotId"),
    capabilityVersion: requireString(raw.capabilityVersion, "ReadContextFrame.capabilityVersion"),
  };
}

function parseSlot(payload: unknown): SlotBinding {
  const raw = requireRecord(payload, "SlotBinding");
  const sourceSpan = raw.sourceSpan === null
    ? null
    : requireTuple(raw.sourceSpan, "SlotBinding.sourceSpan");
  const state = requireEnum(raw.state, ["RESOLVED", "CONFLICTED", "CLEARED"] as const, "SlotBinding.state");
  const value = nullableString(raw.value, "SlotBinding.value");
  if (state === "RESOLVED" && value === null) throw new Error("RESOLVED slot requires a value");
  if (state === "CLEARED" && value !== null) throw new Error("CLEARED slot cannot carry a value");
  return {
    name: requireString(raw.name, "SlotBinding.name"),
    value,
    candidates: parseStringArray(raw.candidates, "SlotBinding.candidates"),
    state,
    provenance: requireEnum(raw.provenance, ["EXPLICIT", "CONFIRMED", "INHERITED", "MODEL_CANDIDATE", "INHERITED_LEGACY"] as const, "SlotBinding.provenance"),
    sourceTurnId: requireString(raw.sourceTurnId, "SlotBinding.sourceTurnId"),
    sourceSpan,
    issues: parseStringArray(raw.issues, "SlotBinding.issues"),
  };
}

function parsePending(payload: unknown): PendingInteraction {
  const raw = requireRecord(payload, "PendingInteraction");
  const expectedFields = parseStringArray(raw.expectedFields, "PendingInteraction.expectedFields");
  if (new Set(expectedFields).size !== expectedFields.length) {
    throw new Error("PendingInteraction.expectedFields must not contain duplicates");
  }
  return {
    kind: requireEnum(raw.kind, ["SLOT_CLARIFICATION", "CAPABILITY_CHOICE", "BATCH_CONFIRMATION", "PLANNER_CONFIRMATION"] as const, "PendingInteraction.kind"),
    frameId: requireString(raw.frameId, "PendingInteraction.frameId"),
    expectedFields,
    stateVersion: requireNonNegativeInteger(raw.stateVersion, "PendingInteraction.stateVersion"),
    registrySnapshotId: requireString(raw.registrySnapshotId, "PendingInteraction.registrySnapshotId"),
    expiresAt: requireString(raw.expiresAt, "PendingInteraction.expiresAt"),
  };
}

function parseLastContext(payload: unknown): LastContext {
  const raw = requireRecord(payload, "LastContext");
  const parameters = requireRecord(raw.parameters, "LastContext.parameters");
  return {
    capabilityId: requireString(raw.capabilityId, "LastContext.capabilityId"),
    parameters: Object.fromEntries(Object.entries(parameters).map(([name, value]) => [name, requireString(value, `LastContext.parameters.${name}`)])),
    missingParameters: parseStringArray(raw.missingParameters, "LastContext.missingParameters"),
    decisionType: requireEnum(raw.decisionType, ["CLARIFY", "SELECT"] as const, "LastContext.decisionType"),
  };
}

function parseTurns(payload: unknown): Turn[] {
  return requireArray(payload, "Session history").map((value) => {
    const turn = requireRecord(value, "Turn");
    return {
      role: requireEnum(turn.role, ["user", "assistant"] as const, "Turn.role"),
      content: requireString(turn.content, "Turn.content", true),
    };
  });
}

function isSessionStateV2(value: unknown): value is SessionStateV2 {
  return isRecord(value) && value.schemaVersion === 2;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, field: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${field} must be an object`);
  return value;
}

function requireArray(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${field} must be an array`);
  return value;
}

function requireString(value: unknown, field: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
    throw new Error(`${field} must be ${allowEmpty ? "a string" : "a non-empty string"}`);
  }
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  return value === null || value === undefined ? null : requireString(value, field);
}

function requireNonNegativeInteger(value: unknown, field: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new Error(`${field} must be a non-negative integer`);
  }
  return value as number;
}

function requireEnum<const T extends readonly string[]>(value: unknown, values: T, field: string): T[number] {
  if (typeof value !== "string" || !values.includes(value)) throw new Error(`${field} is invalid`);
  return value as T[number];
}

function parseStringArray(value: unknown, field: string): string[] {
  return requireArray(value, field).map((item) => requireString(item, field));
}

function requireTuple(value: unknown, field: string): [number, number] {
  if (!Array.isArray(value) || value.length !== 2 ||
      !value.every((item) => Number.isSafeInteger(item)) || value[0] < 0 || value[0] > value[1]) {
    throw new Error(`${field} must be an ordered pair of offsets`);
  }
  return [value[0], value[1]];
}

function unlinkIfPresent(file: string): void {
  if (existsSync(file)) unlinkSync(file);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
