import { describe, expect, it } from "vitest";
import type { AgentRunEvent, AgentRunSnapshot } from "./run-event-schema";
import { applyRunEvent, createInitialSnapshot } from "./run-state-machine";

const started: AgentRunEvent = {
  runId: "run-replay-1",
  sequence: 1,
  timestamp: "2026-08-05T00:00:00.000Z",
  type: "run_started",
  state: "running",
};

describe("applyRunEvent replay integrity", () => {
  it("ignores an identical duplicate delivery", () => {
    const once = applyRunEvent(createInitialSnapshot(started.runId), started);
    const twice = applyRunEvent(once, { ...started });

    expect(twice.events).toHaveLength(1);
    expect(twice.replayIntegrity?.status).toBe("consistent");
  });

  it("preserves the original event and marks a conflicting duplicate", () => {
    const once = applyRunEvent(createInitialSnapshot(started.runId), started);
    const conflict = applyRunEvent(once, { ...started, type: "run_failed", state: "failed" });

    expect(conflict.events).toEqual([started]);
    expect(conflict.state).toBe("running");
    expect(conflict.replayIntegrity).toMatchObject({
      status: "conflict",
      expectedSequence: 2,
      receivedSequence: 1,
    });
  });

  it("keeps the received event but marks a sequence gap as limited evidence", () => {
    const once = applyRunEvent(createInitialSnapshot(started.runId), started);
    const afterGap = applyRunEvent(once, {
      ...started,
      sequence: 3,
      type: "plan_compiled",
    });

    expect(afterGap.events.map((event) => event.sequence)).toEqual([1, 3]);
    expect(afterGap.replayIntegrity).toMatchObject({
      status: "gap",
      expectedSequence: 2,
      receivedSequence: 3,
    });
  });

  it("does not apply an event from another run", () => {
    const snapshot: AgentRunSnapshot = createInitialSnapshot(started.runId);
    const result = applyRunEvent(snapshot, { ...started, runId: "run-other" });

    expect(result).toBe(snapshot);
  });
});
