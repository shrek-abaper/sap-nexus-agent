import { describe, expect, it } from "vitest";
import { buildStreamUrl, lastEventSequence, RECONNECT_DELAY } from "./stream-helpers";
import type { AgentRunEvent } from "@/runtime/run-event-schema";

describe("stream helpers", () => {
  it("buildStreamUrl includes cursor parameter", () => {
    expect(buildStreamUrl("run-123", 0)).toBe("/api/agent-runs/run-123/stream?cursor=0");
    expect(buildStreamUrl("run-123", 5)).toBe("/api/agent-runs/run-123/stream?cursor=5");
  });

  it("lastEventSequence returns max sequence from unsorted events", () => {
    const events: AgentRunEvent[] = [
      { runId: "r1", sequence: 1, timestamp: "t", type: "run_started", state: "running" },
      { runId: "r1", sequence: 3, timestamp: "t", type: "run_completed", state: "completed" },
      { runId: "r1", sequence: 2, timestamp: "t", type: "intent_parsed", state: "intent_parsed" }
    ];
    expect(lastEventSequence(events)).toBe(3);
  });

  it("lastEventSequence returns 0 for empty events", () => {
    expect(lastEventSequence([])).toBe(0);
  });

  it("RECONNECT_DELAY is 500ms", () => {
    expect(RECONNECT_DELAY).toBe(500);
  });
});
