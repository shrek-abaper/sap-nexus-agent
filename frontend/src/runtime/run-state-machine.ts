import type { AgentRunEvent, AgentRunSnapshot } from "./run-event-schema";

export function applyRunEvent(snapshot: AgentRunSnapshot, event: AgentRunEvent): AgentRunSnapshot {
  if (snapshot.runId !== event.runId) {
    return snapshot;
  }

  const expectedSequence = (snapshot.events.at(-1)?.sequence ?? 0) + 1;
  const existing = snapshot.events.find((candidate) => candidate.sequence === event.sequence);
  if (existing) {
    if (JSON.stringify(existing) === JSON.stringify(event)) {
      return {
        ...snapshot,
        replayIntegrity: snapshot.replayIntegrity ?? { status: "consistent" },
      };
    }
    return {
      ...snapshot,
      replayIntegrity: {
        status: "conflict",
        expectedSequence,
        receivedSequence: event.sequence,
        message: `Conflicting replay event at sequence ${event.sequence}`,
      },
    };
  }

  const replayIntegrity = event.sequence === expectedSequence
    ? (snapshot.replayIntegrity ?? { status: "consistent" as const })
    : {
        status: "gap" as const,
        expectedSequence,
        receivedSequence: event.sequence,
        message: `Expected sequence ${expectedSequence}, received ${event.sequence}`,
      };

  return {
    runId: snapshot.runId,
    state: event.state,
    hitlState: event.hitlState ?? snapshot.hitlState,
    events: [...snapshot.events, event].sort((left, right) => left.sequence - right.sequence),
    latestArtifact: event.artifact ?? snapshot.latestArtifact,
    error: event.error ?? snapshot.error,
    replayIntegrity,
  };
}

export function createInitialSnapshot(runId: string): AgentRunSnapshot {
  return {
    runId,
    state: "idle",
    hitlState: "approval_not_required",
    events: [],
    replayIntegrity: { status: "consistent" },
  };
}
