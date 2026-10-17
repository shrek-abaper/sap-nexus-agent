import { NextResponse } from "next/server";
import { dshConversationStore } from "../../../../../../src/server/dsh/conversation-store";
import { getDshRuntime } from "../../../../../../src/server/dsh/registry";
import { DshForkError } from "../../../../../../src/server/dsh/runtime";

// Branches the conversation at a completed turn: the dsh session is forked
// with a balanced completed-turn seed (model context survives) and the
// display history prefix is copied into a new persisted conversation.
export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const id = decodeURIComponent((await context.params).id);

  let payload: { throughMessageId?: unknown };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "invalid JSON" }, { status: 400 });
  }
  if (typeof payload.throughMessageId !== "string" || payload.throughMessageId.length === 0) {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "throughMessageId required" }, { status: 400 });
  }

  const parent = dshConversationStore.get(id);
  if (!parent) {
    return NextResponse.json({ errorType: "NOT_FOUND", message: "conversation not found" }, { status: 404 });
  }
  const cutIndex = parent.messages.findIndex((message) => message.id === payload.throughMessageId);
  if (cutIndex < 0) {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "throughMessageId not in conversation" }, { status: 400 });
  }
  const prefix = parent.messages.slice(0, cutIndex + 1);
  if (prefix[prefix.length - 1]?.role !== "assistant") {
    return NextResponse.json(
      { errorType: "INVALID_REQUEST", message: "branch point must be a completed assistant turn" },
      { status: 400 },
    );
  }
  const completedTurns = prefix.filter((message) => message.role === "user").length;

  const newId = `conv-${crypto.randomUUID()}`;
  try {
    const runtime = await getDshRuntime();
    await runtime.forkSession(id, completedTurns, newId);
  } catch (error) {
    if (error instanceof DshForkError) {
      return NextResponse.json({ errorType: error.code, message: error.message }, { status: 409 });
    }
    return NextResponse.json(
      { errorType: "DSH_FORK_FAILED", message: error instanceof Error ? error.message : "fork failed" },
      { status: 502 },
    );
  }

  const conversation = await dshConversationStore.forkConversation({
    parentId: id,
    throughMessageId: payload.throughMessageId,
    newId,
  });
  if (!conversation) {
    return NextResponse.json({ errorType: "NOT_FOUND", message: "conversation not found" }, { status: 404 });
  }
  return NextResponse.json(conversation);
}
