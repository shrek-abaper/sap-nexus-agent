import { NextResponse } from "next/server";
import { confirmAgentRunBatch } from "../../../../../src/runtime/agent-runtime-adapter";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ runId: string }> }
) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return invalidRequest("Request body must be valid JSON.");
  }
  if (payload && (typeof payload !== "object" || Array.isArray(payload))) {
    return invalidRequest("Batch confirmation accepts an empty JSON object only.");
  }

  const { runId } = await params;
  try {
    await confirmAgentRunBatch(runId);
    return NextResponse.json({ runId });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Batch confirmation failed";
    if (message.includes("not found")) {
      return NextResponse.json({ errorType: "RUN_NOT_FOUND", message }, { status: 404 });
    }
    if (message.includes("already decided") || message.includes("not awaiting batch")) {
      return NextResponse.json({ errorType: "BATCH_CONFLICT", message }, { status: 409 });
    }
    return NextResponse.json({ errorType: "INVALID_BATCH_REQUEST", message }, { status: 400 });
  }
}

function invalidRequest(message: string) {
  return NextResponse.json({ errorType: "INVALID_BATCH_REQUEST", message }, { status: 400 });
}
