import { Context } from "@deepseek-ai/cordis";
import Timer from "@deepseek-ai/cordis-plugin-timer";
import LlmRuntime from "@deepseek-ai/dsh-llm";
import SessionStore from "@deepseek-ai/dsh-session";
import SessionProjectionRegistry from "@deepseek-ai/dsh-session-projection";
import * as sessionInvariant from "@deepseek-ai/dsh-session/invariant";
import SystemPrompt from "@deepseek-ai/dsh-system-prompt";
import ToolRuntime from "@deepseek-ai/dsh-tools";
import AgentRegistry from "@deepseek-ai/dsh-agent";
import * as agentInvariant from "@deepseek-ai/dsh-agent/invariant";
import InvariantRegistry from "@deepseek-ai/dsh-invariants";
import * as scopeInvariant from "@deepseek-ai/dsh-scope/invariant";
import AgentLoop from "@deepseek-ai/dsh-agent-loop";
import * as agentLoopInvariant from "@deepseek-ai/dsh-agent-loop/invariant";
import * as llmRetry from "@deepseek-ai/dsh-llm-retry";
import AgentDefaultModel from "@deepseek-ai/dsh-agent-default-model";

export const DEFAULT_PERSONA = [
  "你是 SAP Nexus 的 DeepSeek Harness 运行时（可替换 harness 层）。",
  "你只允许通过语义工具 diagnose_material_supply 获取 SAP 事实；",
  "不要猜测库存、在途或工厂数据，所有业务数值必须来自工具返回；",
  "用简体中文、简洁地回答。",
].join("");

// Minimal in-process spine, mirroring the published dsh agent spine order
// (Timer -> LLM -> Session -> SystemPrompt -> Tools -> Agent -> Loop) without
// coding-agent surfaces (bash/fs/subagent/workflow). Used by tests and the
// keyless in-process entry; the Loader-based bin uses config/cordis.yml.
export type SpineOptions = {
  personaPrefix?: string;
  defaultModel?: { provider: string; model: string };
};

export async function mountSpine(
  ctx: Context,
  options: SpineOptions = {},
): Promise<Context> {
  const personaPrefix = options.personaPrefix ?? DEFAULT_PERSONA;
  await ctx.plugin(Timer);
  await ctx.plugin(LlmRuntime);
  await ctx.plugin(SessionStore);
  await ctx.plugin(SessionProjectionRegistry);
  await ctx.plugin(InvariantRegistry);
  await ctx.plugin(sessionInvariant);
  await ctx.plugin(SystemPrompt, { personaPrefix });
  await ctx.plugin(ToolRuntime);
  await ctx.plugin(AgentRegistry);
  await ctx.plugin(agentInvariant);
  await ctx.plugin(scopeInvariant);
  await ctx.plugin(agentLoopInvariant);
  await ctx.plugin(llmRetry);
  if (options.defaultModel) {
    await ctx.plugin(AgentDefaultModel, options.defaultModel);
  }
  await ctx.plugin(AgentLoop, { agents: [] });
  return ctx;
}
