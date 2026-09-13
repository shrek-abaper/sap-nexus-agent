// Pure reducers for the WRITE approval lifecycle SSE
// (/api/agent-runs/:runId/stream). Kept out of the component so the event ->
// execution-result mapping is unit-testable without React.

export type SapMessage = {
  type?: string;
  id?: string;
  number?: string;
  message: string;
  field?: string;
};

export type ApprovalExecution =
  | { phase: "executing" }
  | {
      phase: "success" | "failed";
      prNumber?: string;
      commitStatus?: string;
      messages: SapMessage[];
      error?: string;
    };

export type RunStreamEvent = {
  type?: string;
  state?: string;
  artifact?: { payload?: unknown };
  error?: { errorType?: string; message?: string };
};

type ActionResultPayload = {
  success?: boolean;
  data?: { prNumber?: string; commitStatus?: string };
  returnMessages?: SapMessage[];
  errorType?: string;
  error?: string;
};

export function approvalExecutionFromEvent(
  event: RunStreamEvent,
): ApprovalExecution | null {
  if (event.type === "gateway_execute_started") {
    return { phase: "executing" };
  }
  if (event.type === "gateway_execute_completed") {
    const payload = event.artifact?.payload as ActionResultPayload | undefined;
    const data = payload?.data ?? {};
    const failed = payload?.success === false;
    return {
      phase: failed ? "failed" : "success",
      prNumber: data.prNumber,
      commitStatus: data.commitStatus,
      messages: payload?.returnMessages ?? [],
      ...(failed
        ? {
            error: payload.errorType
              ? `${payload.errorType}: ${payload.error ?? ""}`.trim()
              : "SAP 执行失败",
          }
        : {}),
    };
  }
  if (event.type === "run_failed" && event.error?.errorType !== "APPROVAL_REJECTED") {
    return {
      phase: "failed",
      messages: [],
      error: event.error?.message ?? "后台执行失败",
    };
  }
  return null;
}

// Returns true when the event denotes the user rejecting the proposal.
export function isRejectionEvent(event: RunStreamEvent): boolean {
  return (
    (event.type === "approval_state_changed" && event.state === "rejected")
    || (event.type === "run_failed" && event.error?.errorType === "APPROVAL_REJECTED")
  );
}
