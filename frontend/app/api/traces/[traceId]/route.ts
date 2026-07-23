import { NextResponse } from "next/server";
import { getTraceMetadata } from "@/runtime/agent-runtime-adapter";

export async function GET(_request: Request, { params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  return NextResponse.json(getTraceMetadata(traceId));
}
