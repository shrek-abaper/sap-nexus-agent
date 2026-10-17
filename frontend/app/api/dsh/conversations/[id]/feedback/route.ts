import { NextResponse } from "next/server";
import { dshConversationStore } from "../../../../../../src/server/dsh/conversation-store";

// Upserts the latest feedback state for one message. rating toggle semantics
// are computed client-side; this route stores the resulting absolute state.
export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const id = decodeURIComponent((await context.params).id);

  let payload: { messageId?: unknown; rating?: unknown; note?: unknown };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "invalid JSON" }, { status: 400 });
  }
  if (typeof payload.messageId !== "string" || payload.messageId.length === 0) {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "messageId required" }, { status: 400 });
  }
  const rating = payload.rating;
  if (rating !== "up" && rating !== "down" && rating !== null) {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "rating must be up, down, or null" }, { status: 400 });
  }
  const note = payload.note;
  if (note !== undefined && typeof note !== "string") {
    return NextResponse.json({ errorType: "INVALID_REQUEST", message: "note must be a string" }, { status: 400 });
  }

  await dshConversationStore.setFeedback({
    conversationId: id,
    messageId: payload.messageId,
    rating,
    ...(note !== undefined ? { note } : {}),
  });
  return NextResponse.json({ ok: true });
}
