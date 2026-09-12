import { NextResponse } from "next/server";
import { dshConversationStore } from "../../../../src/server/dsh/conversation-store";

// Lists persisted dsh conversations (newest first) for the sidebar.
export async function GET(): Promise<NextResponse> {
  try {
    return NextResponse.json({ conversations: dshConversationStore.list() });
  } catch (error) {
    return NextResponse.json(
      { errorType: "DSH_HISTORY_FAILED", message: error instanceof Error ? error.message : "failed to list conversations" },
      { status: 500 },
    );
  }
}
