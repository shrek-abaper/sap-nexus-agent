import { NextResponse } from "next/server";
import {
  decideAgentRunApproval,
  type ApprovalDecision
} from "../../../../../src/runtime/agent-runtime-adapter";

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
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return invalidRequest("Request body must contain only a decision.");
  }

  const body = payload as Record<string, unknown>;
  if (Object.keys(body).length !== 1 || !isDecision(body.decision)) {
    return invalidRequest("Only decision=approve|reject is accepted.");
  }

  const { runId } = await params;
  try {
    await decideAgentRunApproval(runId, body.decision);
    return NextResponse.json({ runId });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Approval request failed";
    if (message.includes("not found")) {
      return NextResponse.json({ errorType: "RUN_NOT_FOUND", message }, { status: 404 });
    }
    if (message.includes("already decided")) {
      return NextResponse.json({ errorType: "APPROVAL_CONFLICT", message }, { status: 409 });
    }
    return NextResponse.json({ errorType: "INVALID_APPROVAL_REQUEST", message }, { status: 400 });
  }
}

function isDecision(value: unknown): value is ApprovalDecision {
  return value === "approve" || value === "reject";
}

function invalidRequest(message: string) {
  return NextResponse.json({ errorType: "INVALID_APPROVAL_REQUEST", message }, { status: 400 });
}
