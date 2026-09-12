import { randomUUID } from "node:crypto";
import type { Context } from "@deepseek-ai/cordis";
import { SessionId } from "@deepseek-ai/dsh-session";
import { createUserMessage } from "@deepseek-ai/dsh-llm";
import type { Agent } from "@deepseek-ai/dsh-agent";

export type RunTurnInput = {
  task: string;
  provider: string;
  model: string;
  sessionId?: string;
};

export type TurnEndReason = {
  kind: string;
  error?: { code?: string; message?: string };
};

export type RunTurnResult = {
  sessionId: string;
  output: string;
  reason?: TurnEndReason;
  agent: Agent;
  dispose: () => void;
};

// One non-interactive turn: create an agent, deliver the user task, wait for
// the T-A-O loop to settle, and project the final assistant text.
export async function runTurn(
  ctx: Context,
  input: RunTurnInput,
): Promise<RunTurnResult> {
  const sessionId = SessionId(input.sessionId ?? `sapnexus-${randomUUID()}`);
  const created = await ctx.agents.create({
    sessionId,
    meta: { cwd: process.cwd() },
    agentOptions: { provider: input.provider, model: input.model },
  });
  const agent = created.agent;
  const dispose = created.dispose;

  await agent.whenIdle();
  agent.followup(createUserMessage({
    content: [{ type: "text", text: input.task }],
    source: { kind: "user" },
  }));
  await agent.whenIdle();

  const text = assistantText(agent);
  return { sessionId, output: text, reason: turnEndReason(agent), agent, dispose };
}

function turnEndReason(agent: Agent): TurnEndReason | undefined {
  let reason: TurnEndReason | undefined;
  for (const event of agent.session.snapshotEvents()) {
    if (event.type === "turn/end") {
      reason = (event as { data?: { reason?: TurnEndReason } }).data?.reason;
    }
  }
  return reason;
}

// The durable session log envelopes assistant output as
// {type:'assistant/message', data:{message:{content:[...]}}}. The final
// text-bearing assistant message of the turn is the model answer; earlier
// assistant messages may contain only tool calls.
function assistantText(agent: Agent): string {
  let text = "";
  for (const event of agent.session.snapshotEvents()) {
    if (event.type !== "assistant/message") continue;
    const chunks: string[] = [];
    collectText((event as { data?: { message?: { content?: unknown } } }).data?.message?.content, chunks);
    const joined = chunks.join("");
    if (joined.length > 0) text = joined;
  }
  return text;
}

function collectText(content: unknown, sink: string[]): void {
  if (typeof content === "string") {
    sink.push(content);
    return;
  }
  if (Array.isArray(content)) {
    for (const block of content) {
      if (block && typeof block === "object" && (block as { type?: string }).type === "text") {
        const text = (block as { text?: unknown }).text;
        if (typeof text === "string") sink.push(text);
      }
    }
  }
}
