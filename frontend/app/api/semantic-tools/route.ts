import { NextResponse } from "next/server";
import { executeSemanticTool } from "../../../src/runtime/semantic-tools/execute-tool";
import {
  SemanticToolRequestError,
  SemanticToolUpstreamError,
} from "../../../src/runtime/semantic-tools/types";
import { injectPrincipal } from "../../../src/runtime/principal/principal-injector";

// Harness-facing narrow semantic contract for external harnesses (e.g. the
// standalone dsh CLI). The Workbench in-process dsh runtime calls
// executeSemanticTool directly, not over HTTP.
export async function POST(request: Request): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { errorType: "INVALID_REQUEST", message: "Request body must be valid JSON" },
      { status: 400 },
    );
  }

  const principal = injectPrincipal(request);

  try {
    const result = await executeSemanticTool(payload, principal);
    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof SemanticToolRequestError) {
      return NextResponse.json(
        { errorType: error.errorType, message: error.message },
        { status: error.httpStatus },
      );
    }
    if (error instanceof SemanticToolUpstreamError) {
      return NextResponse.json(
        { errorType: error.errorType, message: error.message },
        { status: error.httpStatus },
      );
    }
    return NextResponse.json(
      {
        errorType: "SEMANTIC_TOOL_FAILED",
        message: error instanceof Error ? error.message : "semantic tool execution failed",
      },
      { status: 502 },
    );
  }
}
