import { describe, expect, it } from "vitest";
import { createConversationId } from "../../src/modules/agent-console/conversation-id";

describe("createConversationId", () => {
  it("returns an id with the conv- prefix followed by a uuid", () => {
    const id = createConversationId();

    // The `conv-` prefix is the application convention that scopes a frontend
    // conversation id from a raw platform uuid; dropping it would break log
    // grepping and session-key readability.
    expect(id).toMatch(/^conv-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
  });

  it("returns a different id on each call so a new conversation gets a fresh session", () => {
    const first = createConversationId();
    const second = createConversationId();

    expect(second).not.toBe(first);
  });
});
