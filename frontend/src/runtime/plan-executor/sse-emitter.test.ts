// frontend/src/runtime/plan-executor/sse-emitter.test.ts
import { describe, expect, it } from "vitest";
import type { AgentRunEvent } from "../run-event-schema";
import { NodeState } from "./types";
import { emitNodeStateChanged } from "./sse-emitter";

describe("emitNodeStateChanged", () => {
  it("creates a node_state_changed event with nodeId/fromState/toState/attempt", () => {
    const events: AgentRunEvent[] = [];
    const { event, nextSequence } = emitNodeStateChanged(
      (e) => { events.push(e); },
      "run-1",
      "nodeA",
      NodeState.READY,
      NodeState.VALIDATING,
      0,
      5
    );
    expect(event.type).toBe("node_state_changed");
    expect(event.nodeId).toBe("nodeA");
    expect(event.fromState).toBe(NodeState.READY);
    expect(event.toState).toBe(NodeState.VALIDATING);
    expect(event.attempt).toBe(0);
    expect(event.sequence).toBe(5);
    expect(nextSequence).toBe(6);
    expect(events).toHaveLength(1);
  });

  it("supports null fromState (initial transition)", () => {
    const { event } = emitNodeStateChanged(
      () => {},
      "run-1",
      "nodeB",
      null,
      NodeState.READY,
      0,
      1
    );
    expect(event.fromState).toBeNull();
    expect(event.toState).toBe(NodeState.READY);
  });
});
