import { getAgentRunEvents } from "../../../../../src/runtime/agent-runtime-adapter";
import { injectPrincipal } from "../../../../../src/runtime/principal/principal-injector";
import type { AgentRunEvent } from "../../../../../src/runtime/run-event-schema";

const POLL_INTERVAL = 50;
const encoder = new TextEncoder();

function isTerminal(event: AgentRunEvent): boolean {
  return event.type === "run_completed" || event.type === "run_failed";
}

export async function GET(request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const principal = injectPrincipal(request);
  const { runId } = await params;

  // §3.1: cursor query parameter parsing and validation
  const url = new URL(request.url);
  const cursorParam = url.searchParams.get("cursor");
  let cursor = 0;
  if (cursorParam !== null) {
    const parsed = Number(cursorParam);
    if (!Number.isInteger(parsed) || parsed < 0) {
      return new Response("Invalid cursor", { status: 400 });
    }
    cursor = parsed;
  }

  // Initial existence check (run must have at least run_started)
  const initialEvents = await getAgentRunEvents(runId, principal);
  if (initialEvents.length === 0) {
    return new Response("Run not found", { status: 404 });
  }

  let lastCursor = cursor;
  let cancelled = false;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const poll = async () => {
        if (cancelled) return;
        try {
          const events = await getAgentRunEvents(runId, principal);
          if (events.length === 0) {
            controller.close();
            return;
          }
          // §3.2: replay filtered by sequence > cursor
          const newEvents = events.filter((e) => e.sequence > lastCursor);
          let backpressured = false;
          for (const event of newEvents) {
            // §5.1: backpressure - stop enqueuing if internal buffer is full
            if (controller.desiredSize !== null && controller.desiredSize <= 0) {
              backpressured = true;
              break;
            }
            const chunk = `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
            controller.enqueue(encoder.encode(chunk));
            lastCursor = event.sequence;
          }
          // §4.2: close stream only after terminal event is actually sent.
          // If backpressure broke the loop, remaining events (including the
          // terminal) have not been sent yet; schedule the next poll to drain.
          const lastEvent = events[events.length - 1];
          if (!backpressured && isTerminal(lastEvent)) {
            controller.close();
            return;
          }
          // §1.4: poll for new events
          timeoutId = setTimeout(() => { void poll(); }, POLL_INTERVAL);
        } catch {
          controller.close();
        }
      };
      void poll();
    },
    cancel() {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    }
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive"
    }
  });
}
