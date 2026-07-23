import type { AgentRunEvent, AgentRunSnapshot } from "./run-event-schema";

export function applyRunEvent(snapshot: AgentRunSnapshot, event: AgentRunEvent): AgentRunSnapshot {
  if (snapshot.runId !== event.runId) {
    return snapshot;
  }

  return {
    runId: snapshot.runId,
    state: event.state,
    hitlState: event.hitlState ?? snapshot.hitlState,
    events: [...snapshot.events, event].sort((left, right) => left.sequence - right.sequence),
    latestArtifact: event.artifact ?? snapshot.latestArtifact,
    error: event.error ?? snapshot.error
  };
}

export function createInitialSnapshot(runId: string): AgentRunSnapshot {
  return {
    runId,
    state: "idle",
    hitlState: "approval_not_required",
    events: []
  };
}
