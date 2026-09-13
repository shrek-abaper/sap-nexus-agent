import { describe, expect, it } from "vitest";
import { approvalExecutionFromEvent, isRejectionEvent } from "./approval-execution";

describe("approvalExecutionFromEvent", () => {
  it("maps a successful ActionResult to the PR number and SAP messages", () => {
    const result = approvalExecutionFromEvent({
      type: "gateway_execute_completed",
      artifact: {
        payload: {
          success: true,
          data: { prNumber: "0010137490", commitStatus: "committed" },
          returnMessages: [{ type: "S", message: "Purchase requisition number 10137490 created" }],
        },
      },
    });

    expect(result).toMatchObject({
      phase: "success",
      prNumber: "0010137490",
      commitStatus: "committed",
    });
    expect(result?.phase === "success" ? result.messages : []).toHaveLength(1);
  });

  it("maps a failed ActionResult with its error type", () => {
    const result = approvalExecutionFromEvent({
      type: "gateway_execute_completed",
      artifact: {
        payload: {
          success: false,
          data: {},
          returnMessages: [],
          errorType: "SAP_BUSINESS_ERROR",
          error: "boom",
        },
      },
    });

    expect(result).toMatchObject({ phase: "failed", error: "SAP_BUSINESS_ERROR: boom" });
  });

  it("signals executing on gateway_execute_started", () => {
    expect(approvalExecutionFromEvent({ type: "gateway_execute_started" }))
      .toEqual({ phase: "executing" });
  });

  it("turns run_failed into a failure but leaves rejection to the caller", () => {
    expect(approvalExecutionFromEvent({
      type: "run_failed",
      error: { errorType: "RUNTIME", message: "broken" },
    })).toMatchObject({ phase: "failed", error: "broken" });

    expect(approvalExecutionFromEvent({
      type: "run_failed",
      error: { errorType: "APPROVAL_REJECTED", message: "rejected" },
    })).toBeNull();
  });

  it("ignores unrelated events", () => {
    expect(approvalExecutionFromEvent({ type: "narrative_created" })).toBeNull();
  });
});

describe("isRejectionEvent", () => {
  it("recognizes the rejected approval state and terminal rejection", () => {
    expect(isRejectionEvent({ type: "approval_state_changed", state: "rejected" })).toBe(true);
    expect(isRejectionEvent({
      type: "run_failed",
      error: { errorType: "APPROVAL_REJECTED", message: "no" },
    })).toBe(true);
    expect(isRejectionEvent({ type: "approval_state_changed", state: "approved" })).toBe(false);
  });
});
