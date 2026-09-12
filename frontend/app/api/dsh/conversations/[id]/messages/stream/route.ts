import { dshModelConfigured, getDshRuntime } from "../../../../../../../src/server/dsh/registry";
import { dshConversationStore } from "../../../../../../../src/server/dsh/conversation-store";
import type { DshStreamEvent } from "../../../../../../../src/server/dsh/runtime";

// SSE over POST: token deltas + tool lifecycle, then one final event.
// The browser consumes it with fetch + ReadableStream (EventSource cannot POST).
export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await context.params;
  let payload: { text?: unknown };
  try {
    payload = await request.json();
  } catch {
    return Response.json({ errorType: "INVALID_REQUEST", message: "invalid JSON" }, { status: 400 });
  }
  if (typeof payload.text !== "string" || payload.text.trim().length === 0) {
    return Response.json({ errorType: "INVALID_REQUEST", message: "text must be a non-empty string" }, { status: 400 });
  }
  if (!dshModelConfigured()) {
    return Response.json(
      { errorType: "DSH_MODEL_NOT_CONFIGURED", message: "Set SAP_NEXUS_LLM_API_KEY (or LLM_API_KEY) in the server environment." },
      { status: 503 },
    );
  }

  const encoder = new TextEncoder();
  const send = (event: unknown): Uint8Array => encoder.encode(`data: ${JSON.stringify(event)}\n\n`);

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const userText = String(payload.text).trim();
      try {
        const runtime = await getDshRuntime();
        let finalEvent: Extract<DshStreamEvent, { type: "final" }> | undefined;
        let errorEvent: Extract<DshStreamEvent, { type: "error" }> | undefined;
        for await (const event of runtime.streamMessage(id, userText)) {
          controller.enqueue(send(event));
          if (event.type === "final") finalEvent = event;
          if (event.type === "error") errorEvent = event;
          if (event.type === "final" || event.type === "error") break;
        }
        // Persist the completed turn for the sidebar/history.
        if (finalEvent || errorEvent) {
          await dshConversationStore.addTurn({
            conversationId: id,
            userText,
            assistantText: finalEvent?.output ?? "",
            assistantToolCalls: finalEvent?.toolCalls,
            ...(errorEvent ? { assistantError: errorEvent.message } : {}),
          });
        }
      } catch (error) {
        controller.enqueue(send({
          type: "error",
          message: error instanceof Error ? error.message : "dsh stream failed",
        }));
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
    },
  });
}
