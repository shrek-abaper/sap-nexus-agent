import { Context } from "@deepseek-ai/cordis";
import Timer from "@deepseek-ai/cordis-plugin-timer";
import LlmRuntime, { type LlmAdapter } from "@deepseek-ai/dsh-llm";
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

export type DshRuntime = {
  sendMessage(conversationId: string, text: string): Promise<DshTurnResult>;
  dispose(): Promise<void>;
};

type AgentSession = {
  agent: Agent;
  dispose: () => void;
  pending: ToolCallRecord[];
};

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

function toolText(value: SemanticToolResponse): string {
  const lines: string[] = [];
  if (value.narrative.summary) lines.push(value.narrative.summary);
  lines.push(`[status=${value.status}]`);
  if (value.approval) {
    const p = value.approval.parameters;
    lines.push(`审批句柄 approvalId=${value.approval.approvalId} expiresAt=${value.approval.expiresAt}`);
    lines.push(`PR 参数: 物料=${p.material} 工厂=${p.plant} 数量=${p.quantity} 单位=${p.unit} 交货=${p.delivery_date} 采购组=${p.purchasing_group}`);
    lines.push("这是待审批提案，尚未写入 SAP；请提示用户在审批卡片上批准或拒绝。");
  }
  for (const limitation of value.limitations) lines.push(`- ${limitation}`);
  if (value.error) lines.push(`error: ${value.error.errorType}: ${value.error.message}`);
  return lines.join("\n");
}

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
      output: { schema: { type: "json" }, render: (_args, value) => [{ type: "text", text: toolText(value as SemanticToolResponse) }] },
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
          return result as unknown as JsonValue;
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
    const created = await ctx.agents.create({
      sessionId,
      meta: { cwd: process.cwd() },
      agentOptions: { provider: options.provider, model: options.model },
    });
    const session: AgentSession = { agent: created.agent, dispose: created.dispose, pending: [] };
    sessions.set(key, session);
    return session;
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
    },
    async dispose() {
      for (const session of sessions.values()) session.dispose();
      sessions.clear();
      await ctx.fiber.dispose();
    },
  };
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
