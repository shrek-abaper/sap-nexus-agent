import { Context } from "@deepseek-ai/cordis";
import Timer from "@deepseek-ai/cordis-plugin-timer";
import LlmRuntime, { LlmAdapter, type LlmProviderInfo } from "@deepseek-ai/dsh-llm";
import SessionStore from "@deepseek-ai/dsh-session";
import SessionProjectionRegistry from "@deepseek-ai/dsh-session-projection";
import * as sessionInvariant from "@deepseek-ai/dsh-session/invariant";
import SystemPrompt from "@deepseek-ai/dsh-system-prompt";
import ToolRuntime, { defineTool, type ParameterSchemaSpec } from "@deepseek-ai/dsh-tools";
import AgentRegistry, { type Agent } from "@deepseek-ai/dsh-agent";
import * as agentInvariant from "@deepseek-ai/dsh-agent/invariant";
import InvariantRegistry from "@deepseek-ai/dsh-invariants";
import * as scopeInvariant from "@deepseek-ai/dsh-scope/invariant";
import AgentLoop from "@deepseek-ai/dsh-agent-loop";
import * as agentLoopInvariant from "@deepseek-ai/dsh-agent-loop/invariant";
import * as llmRetry from "@deepseek-ai/dsh-llm-retry";
import { SessionId } from "@deepseek-ai/dsh-session";
import { createUserMessage } from "@deepseek-ai/dsh-llm";
import type { JsonValue } from "../../shared/types/artifacts";
import type { SemanticToolResponse } from "../../runtime/semantic-tools/types";

export const DEFAULT_DSH_PERSONA = [
  "你是 SAP Nexus 的 DeepSeek Harness 运行时，也是本工作台唯一的对话运行时。",
  "你只能通过提供的语义工具获取 SAP 业务事实（库存/采购订单/销售订单/应收应付/补货建议）。",
  "禁止猜测任何库存、在途、金额、工厂或凭证数据；所有业务数值必须引用工具返回。",
  "当工具要求澄清（缺少物料/工厂/客户/供应商/公司代码等）时，用简体中文向用户追问缺失项。",
  "涉及补货写入时，先依据工具返回的审批卡片向用户复述参数并请求批准，不要声称已经创建。",
  "回答简洁、分点清晰，币种与单位随数值给出。",
  "严格遵守 Markdown 排版规范：每个标题（#）、列表项（- 或数字.）、引用（>）、分隔线（---）都必须独占一行，其前后各留一个空行；列表项的 - 后必须有一个空格；不要把多个标题或列表项写在同一行；不要输出裸露的 #、*、- 符号。",
].join("");

export type ToolCallRecord = {
  callId: string;
  name: string;
  args: unknown;
  status: "completed" | "failed" | "awaiting_approval";
  result?: SemanticToolResponse;
  error?: string;
};

export type DshTurnResult = {
  output: string;
  toolCalls: ToolCallRecord[];
  reasonKind?: string;
};

export type ToolHandler = (args: Record<string, unknown>) => Promise<SemanticToolResponse>;

export type CreateDshRuntimeOptions = {
  provider: string;
  model: string;
  adapter: LlmAdapter;
  handlers: Record<string, ToolHandler>;
  persona?: string;
};

export type DshStreamEvent =
  // phase: "reasoning" = before/while tools run (collapsed trace);
  // "answer" = after all tool results returned (the visible final answer).
  | { type: "delta"; text: string; phase: "reasoning" | "answer" }
  | { type: "tool-start"; callId: string; name: string; args: unknown }
  | { type: "tool-result"; callId: string; name: string; status: ToolCallRecord["status"]; result?: SemanticToolResponse; error?: string }
  | { type: "final"; output: string; toolCalls: ToolCallRecord[]; reasonKind?: string }
  | { type: "error"; message: string };

export type DshRuntime = {
  sendMessage(conversationId: string, text: string): Promise<DshTurnResult>;
  streamMessage(conversationId: string, text: string): AsyncIterable<DshStreamEvent>;
  dispose(): Promise<void>;
};

type AgentSession = {
  agent: Agent;
  dispose: () => void;
  pending: ToolCallRecord[];
  /** Active token sink for the current streamed turn, if any. */
  sink: ((event: DshStreamEvent) => void) | null;
  /** True once at least one tool call started; later text deltas are the answer. */
  toolStarted: boolean;
  /**
   * Whether the CURRENT model step is the final answer step. A turn with no
   * tools is answer from the first step; after a tool runs, the loop starts
   * another step which becomes the answer step (set via session/event).
   */
  answerStep: boolean;
};

// Per-session adapter: a unique LLM provider route per conversation taps the
// model stream without ambiguity across concurrent conversations.
class SessionTappingAdapter extends LlmAdapter {
  constructor(
    private readonly inner: LlmAdapter,
    private readonly session: AgentSession,
    private readonly providerRoute: string,
  ) {
    super();
  }
  override resolveModel(provider: string, model: string) {
    return this.inner.resolveModel(provider, model);
  }
  override providerInfo(provider: string): LlmProviderInfo {
    return this.inner.providerInfo(provider);
  }
  async *stream(generateOptions: Parameters<LlmAdapter["stream"]>[0]) {
    for await (const chunk of this.inner.stream(generateOptions)) {
      if (
        chunk.type === "text-delta"
        && typeof chunk.text === "string"
        && chunk.text
        && this.session.sink
      ) {
        this.session.sink({
          type: "delta",
          text: chunk.text,
          phase: this.session.answerStep ? "answer" : "reasoning",
        });
      }
      yield chunk;
    }
  }
  get route() { return this.providerRoute; }
}

const TOOL_SPECS: Record<string, ParameterSchemaSpec> = {
  diagnose_material_supply: {
    utterance: { type: "string", required: true, description: "用户完整的自然语言问题" },
    material: { type: "string", description: "物料编号，如 DEMOA1" },
    plant: { type: "string", description: "工厂编码，如 1000" },
  },
  review_customer_exposure: {
    utterance: { type: "string", required: true, description: "用户完整的自然语言问题" },
    customerNumber: { type: "string", required: true, description: "客户编号" },
    companyCode: { type: "string", description: "公司代码（应收未清项必需）" },
  },
  review_vendor_exposure: {
    utterance: { type: "string", required: true, description: "用户完整的自然语言问题" },
    vendor: { type: "string", required: true, description: "供应商编号，如 DEMOV1" },
    companyCode: { type: "string", required: true, description: "公司代码，如 1000" },
  },
  propose_replenishment: {
    utterance: { type: "string", required: true, description: "用户完整的自然语言问题" },
    material: { type: "string", required: true, description: "物料编号" },
    plant: { type: "string", required: true, description: "工厂编码" },
    requiredQuantity: { type: "number", required: true, description: "目标需求量（数值）" },
    targetDate: { type: "string", required: true, description: "目标交货日期 YYYY-MM-DD" },
    purchasingGroup: { type: "string", required: true, description: "采购组（1-3 字符，如 601）" },
  },
};

export async function createDshRuntime(options: CreateDshRuntimeOptions): Promise<DshRuntime> {
  const ctx = new Context();
  await ctx.plugin(Timer);
  await ctx.plugin(LlmRuntime);
  await ctx.plugin(SessionStore);
  await ctx.plugin(SessionProjectionRegistry);
  await ctx.plugin(InvariantRegistry);
  await ctx.plugin(sessionInvariant);
  await ctx.plugin(SystemPrompt, { personaPrefix: options.persona ?? DEFAULT_DSH_PERSONA });
  await ctx.plugin(ToolRuntime);
  await ctx.plugin(AgentRegistry);
  await ctx.plugin(agentInvariant);
  await ctx.plugin(scopeInvariant);
  await ctx.plugin(agentLoopInvariant);
  await ctx.plugin(llmRetry);
  await ctx.plugin(AgentLoop, { agents: [] });
  ctx.llm.registerAdapter([options.provider], options.adapter);

  const sessions = new Map<string, AgentSession>();

  for (const [name, handler] of Object.entries(options.handlers)) {
    const spec = TOOL_SPECS[name];
    if (!spec) throw new Error(`No tool spec registered for ${name}`);
    ctx.tools.register(defineTool({
      name,
      description: toolDescription(name),
      parameters: spec,
      // The model receives a DETERMINISTIC textual result (authoritative
      // narrative + explicit fact lines), not raw JSON: models otherwise
      // misread nested evidence/mrpElementLines fields (e.g. a null
      // elementQty vs the authoritative fact value). The structured value is
      // retained in session.pending and drives the UI fact cards.
      output: { schema: { type: "json" }, render: (_args, value) => {
        const result = value as SemanticToolResponse;
        return [{ type: "text", text: resultToModelText(result) }];
      } },
      async execute(args, exec): Promise<JsonValue> {
        const session = exec.agent ? sessions.get(exec.agent.session.id) : undefined;
        const record: ToolCallRecord = {
          callId: exec.callId,
          name,
          args,
          status: "completed",
        };
        try {
          const result = await handler(args);
          record.result = result;
          record.status = result.status === "awaiting_approval" ? "awaiting_approval" : "completed";
          session?.pending.push(record);
          // dsh-tools requires a lossless-JSON value: undefined optional
          // fields (traceId/factId/…) would otherwise fail the snapshot and
          // replace the whole tool result with an error the model then reads
          // as "no data". Strip them to plain JSON.
          return JSON.parse(JSON.stringify(result)) as JsonValue;
        } catch (error) {
          record.status = "failed";
          record.error = error instanceof Error ? error.message : String(error);
          session?.pending.push(record);
          throw error;
        }
      },
    }));
  }


  async function ensureSession(conversationId: string): Promise<AgentSession> {
    const key = `dsh-${conversationId}`;
    const existing = sessions.get(key);
    if (existing) return existing;
    const sessionId = SessionId(key);
    const session: AgentSession = {
      agent: null as unknown as Agent,
      dispose: () => undefined,
      pending: [],
      sink: null,
      toolStarted: false,
      answerStep: false,
    };
    const route = `sapnexus-${key}`.replace(/[^a-zA-Z0-9_-]/g, "");
    const tapping = new SessionTappingAdapter(options.adapter, session, route);
    ctx.llm.registerAdapter([route], tapping);
    const created = await ctx.agents.create({
      sessionId,
      meta: { cwd: process.cwd() },
      agentOptions: { provider: route, model: options.model },
    });
    session.agent = created.agent;
    session.dispose = created.dispose;
    sessions.set(key, session);
    return session;
  }

  function finalizeTurn(session: AgentSession): DshTurnResult {
    const agent = session.agent;
    let output = "";
    for (const event of agent.session.snapshotEvents()) {
      if (event.type === "assistant/message") {
        const chunks: string[] = [];
        const content = (event as { data?: { message?: { content?: unknown } } }).data?.message?.content;
        if (Array.isArray(content)) {
          for (const block of content) {
            if (block && typeof block === "object" && (block as { type?: string }).type === "text") {
              const t = (block as { text?: unknown }).text;
              if (typeof t === "string") chunks.push(t);
            }
          }
        }
        if (chunks.join("").trim().length > 0) output = chunks.join("");
      }
    }
    let reasonKind: string | undefined;
    for (const event of agent.session.snapshotEvents()) {
      if (event.type === "turn/end") {
        reasonKind = (event as { data?: { reason?: { kind?: string } } }).data?.reason?.kind;
      }
    }
    return { output, toolCalls: [...session.pending], reasonKind };
  }

  // Live stream for one turn: token deltas (agent/assistant-stream frames),
  // tool call/result (session events), then the final extracted answer.
  async function* streamTurn(conversationId: string, text: string): AsyncGenerator<DshStreamEvent> {
    const session = await ensureSession(conversationId);
    session.pending = [];
    const agent = session.agent;
    const sessionId = agent.session.id;
    const queue: DshStreamEvent[] = [];
    let wake: (() => void) | null = null;

    const push = (event: DshStreamEvent) => {
      queue.push(event);
      wake?.();
    };
    const wait = () => new Promise<void>((resolve) => { wake = resolve; });

    // Tool lifecycle from the durable session log (root bus; filter by subject).
    const pendingRecordNames: string[] = [];
    const onSessionEvent = (subject: unknown, event: { type?: string; data?: unknown }) => {
      const subjectSession = subject as { id?: string };
      if (subjectSession?.id !== sessionId) return;
      if (event.type === "step/start") {
        // A fresh step is the candidate final-answer step until/unless it
        // calls a tool. A tool-less turn (plain answer) therefore streams
        // directly as the answer, while pre-tool narration stays reasoning.
        session.answerStep = true;
      }
      if (event.type === "tool/call") {
        const data = event.data as { callId?: string; name?: string; arguments?: string };
        let args: unknown;
        try { args = data.arguments ? JSON.parse(data.arguments) : undefined; } catch { args = data.arguments; }
        session.toolStarted = true;
        session.answerStep = false;
        push({ type: "tool-start", callId: data.callId ?? "", name: data.name ?? "", args });
      } else if (event.type === "tool/result") {
        // The structured SemanticToolResponse is recorded by the execute
        // wrapper (session.pending); the durable session event only carries
        // model-facing text, so pair by arrival order on the tool name.
        const name = pendingRecordNames.length < session.pending.length
          ? session.pending[pendingRecordNames.length]?.name
          : undefined;
        const record = [...session.pending].reverse().find((item) => item.name === name)
          ?? session.pending[session.pending.length - 1];
        pendingRecordNames.push(name ?? "");
        push({
          type: "tool-result",
          callId: "",
          name: record?.name ?? name ?? "",
          status: record?.status ?? "completed",
          result: record?.result,
          error: record?.error,
        });
      }
    };

    const sessionListener = ctx.on("session/event", onSessionEvent, { global: true });

    let done = false;
    let failure: unknown;
    session.sink = push;
    session.toolStarted = false;
    session.answerStep = false;
    const turn = (async () => {
      await agent.whenIdle();
      agent.followup(createUserMessage({
        content: [{ type: "text", text }],
        source: { kind: "user" },
      }));
      await agent.whenIdle();
    })();
    turn.then(() => { done = true; wake?.(); }, (error) => { done = true; failure = error; wake?.(); });

    try {
      // Pair tool-result events with their tool-start by arrival order.
      const pendingStarts: { callId: string; name: string }[] = [];
      const drain = function* (): Generator<DshStreamEvent> {
        while (queue.length > 0) {
          const event = queue.shift()!;
          if (event.type === "tool-start") pendingStarts.push({ callId: event.callId, name: event.name });
          if (event.type === "tool-result") {
            const start = pendingStarts.shift();
            yield start ? { ...event, callId: start.callId, name: start.name } : event;
          } else {
            yield event;
          }
        }
      };
      while (!done || queue.length > 0) {
        yield* drain();
        if (done) break;
        await wait();
      }
      yield* drain();
      if (failure) throw failure;
      const result = finalizeTurn(session);
      yield { type: "final", output: result.output, toolCalls: result.toolCalls, reasonKind: result.reasonKind };
    } catch (error) {
      yield { type: "error", message: error instanceof Error ? error.message : String(error) };
    } finally {
      session.sink = null;
      try { sessionListener(); } catch { /* already disposed */ }
      await turn.catch(() => undefined);
    }
  }

  return {
    async sendMessage(conversationId: string, text: string): Promise<DshTurnResult> {
      const session = await ensureSession(conversationId);
      session.pending = [];
      const agent = session.agent;
      await agent.whenIdle();
      agent.followup(createUserMessage({
        content: [{ type: "text", text }],
        source: { kind: "user" },
      }));
      await agent.whenIdle();
      return finalizeTurn(session);
    },
    streamMessage(conversationId: string, text: string): AsyncIterable<DshStreamEvent> {
      return { [Symbol.asyncIterator]: () => streamTurn(conversationId, text) };
    },
    async dispose() {
      for (const session of sessions.values()) session.dispose();
      sessions.clear();
      await ctx.fiber.dispose();
    },
  };
}

// Deterministic, unambiguous tool-result text for the model. The numbers are
// taken from the authoritative mapped facts (value/unit/asOf), then the
// server-generated narrative. JSON internals are intentionally omitted so the
// model cannot confuse a null MRP elementQty with the fact value.
function resultToModelText(result: SemanticToolResponse): string {
  const lines: string[] = [];
  lines.push(`状态: ${result.status}`);
  for (const fact of result.facts) {
    const value = fact.value !== null
      ? `${fact.value}${fact.unit ? " " + fact.unit : ""}`
      : fact.evidence?.map((row) => evidenceAmount(row)).filter(Boolean).join("; ") || "(无数值)";
    const subject = [fact.material, fact.plant].filter(Boolean).join("/");
    lines.push(`事实${subject ? `（${subject}）` : ""}: ${value}${fact.asOf ? `，数据日期 ${fact.asOf.slice(0, 10)}` : ""}`);
  }
  if (result.narrative.summary) lines.push("", result.narrative.summary);
  if (result.approval) {
    const p = result.approval.parameters;
    lines.push("", `待审批提案 approvalId=${result.approval.approvalId}，有效期至 ${result.approval.expiresAt}`,
      `PR 参数: 物料=${p.material} 工厂=${p.plant} 数量=${p.quantity} 单位=${p.unit} 交货=${p.delivery_date} 采购组=${p.purchasing_group}`,
      "尚未写入 SAP，必须等待用户在审批卡片上批准或拒绝。");
  }
  for (const limitation of result.limitations) lines.push(`限制: ${limitation}`);
  if (result.error) lines.push(`错误: ${result.error.errorType}: ${result.error.message}`);
  return lines.join("\n");
}

function evidenceAmount(row: unknown): string {
  if (!row || typeof row !== "object") return "";
  const r = row as Record<string, unknown>;
  const amount = r.amtDoccur ?? r.netValue ?? r.orderQuantity;
  const currency = r.currency ?? r.purchaseOrderUnit ?? r.unit;
  return amount !== undefined && amount !== null ? `${amount}${currency ? " " + String(currency) : ""}` : "";
}

function toolDescription(name: string): string {
  switch (name) {
    case "diagnose_material_supply":
      return "诊断物料供应：回答某物料在某工厂的可用库存与在途采购订单（只读）。";
    case "review_customer_exposure":
      return "客户敞口：查询某客户的销售订单（净值/币种）与应收未清项（金额/到期日，需公司代码）。只读。";
    case "review_vendor_exposure":
      return "供应商敞口：查询某供应商的应付未清项（金额/币种/到期基准日，需公司代码）。只读。";
    case "propose_replenishment":
      return "补货建议：依据库存与目标需求量计算缺口，生成一个待人工审批的采购申请提案（不会直接写入）。";
    default:
      return name;
  }
}
