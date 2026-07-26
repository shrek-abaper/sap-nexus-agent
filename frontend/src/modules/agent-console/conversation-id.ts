/**
 * Creates a fresh conversation id that scopes a multi-turn agent session.
 *
 * The `conv-` prefix marks the id as a frontend-owned conversation key (as
 * opposed to a server run id) so it stays greppable in logs and trace
 * payloads. The suffix is a platform uuid.
 */
export function createConversationId(): string {
  return `conv-${crypto.randomUUID()}`;
}
