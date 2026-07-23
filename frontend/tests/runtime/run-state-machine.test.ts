import { describe, expect, it } from "vitest";
import { applyRunEvent } from "../../src/runtime/run-state-machine";
import type { AgentRunSnapshot, HumanInTheLoopState } from "../../src/runtime/run-event-schema";

const initial: AgentRunSnapshot = {
  runId: "run-1",
  state: "idle",
  events: [],
  hitlState: "approval_not_required"
};

describe("applyRunEvent", () => {
  it("advances a successful read-only run", () => {
    const next = applyRunEvent(initial, {
      runId: "run-1",
      sequence: 1,
      timestamp: "2026-06-20T00:00:00.000Z",
      type: "run_started",
      state: "running"
    });

    expect(next.state).toBe("running");
    expect(next.events).toHaveLength(1);
    expect(next.hitlState).toBe("approval_not_required");
  });

  it("enters failed state when an error event arrives", () => {
    const next = applyRunEvent(initial, {
      runId: "run-1",
      sequence: 1,
      timestamp: "2026-06-20T00:00:00.000Z",
      type: "run_failed",
      state: "failed",
      error: {
        errorType: "INVALID_PARAMETER",
        message: "参数不合法",
        stage: "validating"
      }
    });

    expect(next.state).toBe("failed");
    expect(next.error?.errorType).toBe("INVALID_PARAMETER");
  });

  it.each<HumanInTheLoopState>([
    "approval_required",
    "awaiting_human_approval",
    "approved",
    "rejected",
    "expired"
  ])("represents future HITL state %s without changing execution behavior", (hitlState) => {
    const next = applyRunEvent(initial, {
      runId: "run-1",
      sequence: 1,
      timestamp: "2026-06-20T00:00:00.000Z",
      type: "approval_state_changed",
      state: "approval_checked",
      hitlState
    });

    expect(next.state).toBe("approval_checked");
    expect(next.hitlState).toBe(hitlState);
  });
});
