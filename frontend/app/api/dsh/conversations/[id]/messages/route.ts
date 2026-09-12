import { NextResponse } from "next/server";
import { getDshRuntime, dshModelConfigured } from "../../../../../../src/server/dsh/registry";

// One dsh conversation turn: the in-process runtime runs the model T-A-O loop
// and returns the assistant text plus structured tool calls (fact/approval
// cards). WRITE decisions are NOT taken here — they post to the existing
// /api/agent-runs/[runId]/approval route with the returned handle.
export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const { id } = await context.params;
  if (!id || typeof id !== "string") {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "conversation id required" }, { status: 400 });
  }

  let payload: { text?: unknown };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "invalid JSON" }, { status: 400 });
  }
  if (typeof payload.text !== "string" || payload.text.trim().length === 0) {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "text must be a non-empty string" }, { status: 400 });
  }
  if (!dshModelConfigured()) {
    return NextResponse.json(
      { errorType: "DSH_MODEL_NOT_CONFIGURED", message: "Set SAP_NEXUS_LLM_API_KEY (or LLM_API_KEY) in the server environment." },
      { status: 503 },
    );
  }

  try {
    const runtime = await getDshRuntime();
    const turn = await runtime.sendMessage(id, payload.text.trim());
    return NextResponse.json({
      conversationId: id,
      output: turn.output,
      toolCalls: turn.toolCalls,
      reasonKind: turn.reasonKind,
    });
  } catch (error) {
    return NextResponse.json(
      { errorType: "DSH_TURN_FAILED", message: error instanceof Error ? error.message : "dsh turn failed" },
      { status: 502 },
    );
  }
}
