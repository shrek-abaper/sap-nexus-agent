import type { AgentRunEvent } from "@/runtime/run-event-schema";

export const RECONNECT_DELAY = 500;

export function buildStreamUrl(serverRunId: string, cursor: number): string {
  return `/api/agent-runs/${serverRunId}/stream?cursor=${cursor}`;
}

export function lastEventSequence(events: AgentRunEvent[]): number {
  return events.length > 0 ? Math.max(...events.map((e) => e.sequence)) : 0;
}
