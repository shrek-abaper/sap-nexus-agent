import { NextResponse } from "next/server";
import { createAgentRun } from "@/runtime/agent-runtime-adapter";

export async function POST(request: Request) {
  const payload = await request.json();

  try {
    const result = await createAgentRun({
      query: String(payload.query ?? ""),
      rfcName: payload.rfcName ? String(payload.rfcName) : undefined
    });
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { errorType: "INVALID_REQUEST", message: error instanceof Error ? error.message : "Invalid request" },
      { status: 400 }
    );
  }
}
