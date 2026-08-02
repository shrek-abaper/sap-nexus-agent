import { getAgentRunEvents } from "@/runtime/agent-runtime-adapter";
import { injectPrincipal } from "../../../../../src/runtime/principal/principal-injector";

export async function GET(request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const principal = injectPrincipal(request);
  const { runId } = await params;
  const events = await getAgentRunEvents(runId, principal);
  const body = events.map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");

  return new Response(body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive"
    }
  });
}
