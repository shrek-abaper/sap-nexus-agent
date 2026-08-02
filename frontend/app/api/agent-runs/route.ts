import { NextResponse } from "next/server";
import { createAgentRun } from "../../../src/runtime/agent-runtime-adapter";
import { injectPrincipal } from "../../../src/runtime/principal/principal-injector";

export async function POST(request: Request) {
  const payload = await request.json();
  const principal = injectPrincipal(request);

  try {
    const result = await createAgentRun({
      query: String(payload.query ?? ""),
      rfcName: payload.rfcName ? String(payload.rfcName) : undefined,
      conversationId: payload.conversationId ? String(payload.conversationId) : undefined,
      principal
    });
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { errorType: "INVALID_REQUEST", message: error instanceof Error ? error.message : "Invalid request" },
      { status: 400 }
    );
  }
}
