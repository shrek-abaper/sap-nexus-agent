import { NextResponse } from "next/server";
import { dshConversationStore } from "../../../../../src/server/dsh/conversation-store";

const conversationIdParam = async (context: { params: Promise<{ id: string }> }) =>
  decodeURIComponent((await context.params).id);

// Returns one persisted conversation with its messages for history replay.
export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const id = await conversationIdParam(context);
  const conversation = dshConversationStore.get(id);
  if (!conversation) {
    return NextResponse.json({ errorType: "NOT_FOUND", message: "conversation not found" }, { status: 404 });
  }
  return NextResponse.json(conversation);
}

// Deletes one conversation and all its messages from persistence.
export async function DELETE(
  _request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const id = await conversationIdParam(context);
  const removed = await dshConversationStore.remove(id);
  if (!removed) {
    return NextResponse.json({ errorType: "NOT_FOUND", message: "conversation not found" }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}
