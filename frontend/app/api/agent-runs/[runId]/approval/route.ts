import { NextResponse } from "next/server";
import {
  decideAgentRunApproval,
  type ApprovalDecision
} from "../../../../../src/runtime/agent-runtime-adapter";
import { injectPrincipal } from "../../../../../src/runtime/principal/principal-injector";
import { ActionGovernanceError } from "../../../../../src/runtime/action-governance/action-governance";

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
  if (Object.keys(body).length !== 2 || !isApprovalId(body.approvalId) || !isDecision(body.decision)) {
    return invalidRequest("Only approvalId and decision=approve|reject are accepted.");
  }

  const principal = injectPrincipal(request);
  const { runId } = await params;
  try {
    await decideAgentRunApproval(runId, body.approvalId, body.decision, principal);
    return NextResponse.json({ runId });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Approval request failed";
    if (error instanceof ActionGovernanceError) {
      const status = error.errorType === "APPROVAL_RUN_NOT_FOUND"
        ? 404
        : error.errorType === "APPROVAL_CONFLICT" || error.errorType === "ACTION_CONTINUATION_IN_PROGRESS"
          ? 409
          : 400;
      return NextResponse.json({ errorType: error.errorType, message }, { status });
    }
    if (message.includes("not found")) {
      return NextResponse.json({ errorType: "RUN_NOT_FOUND", message }, { status: 404 });
    }
    if (message.includes("already decided")) {
      return NextResponse.json({ errorType: "APPROVAL_CONFLICT", message }, { status: 409 });
    }
    if (message.includes("approval identity")) {
      return NextResponse.json({ errorType: "APPROVAL_SUBJECT_MISMATCH", message }, { status: 400 });
    }
    return NextResponse.json({ errorType: "INVALID_APPROVAL_REQUEST", message }, { status: 400 });
  }
}

function isDecision(value: unknown): value is ApprovalDecision {
  return value === "approve" || value === "reject";
}

function isApprovalId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function invalidRequest(message: string) {
  return NextResponse.json({ errorType: "INVALID_APPROVAL_REQUEST", message }, { status: 400 });
}
