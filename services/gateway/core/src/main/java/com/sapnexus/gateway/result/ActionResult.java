package com.sapnexus.gateway.result;

import java.util.List;

public record ActionResult(
        String traceId,
        String capabilityId,
        boolean success,
        String prNumber,
        CommitStatus commitStatus,
        List<SapReturnMessage> returnMessages,
        long durationMs,
        ErrorType errorType
) {
    public static ActionResult fromExecutionResult(ExecutionResult result) {
        Object rawPrNumber = result.data().get("prNumber");
        String prNumber = rawPrNumber == null ? "" : String.valueOf(rawPrNumber);
        CommitStatus status = commitStatusFrom(result);
        return new ActionResult(
                result.traceId(),
                result.capabilityId(),
                result.success(),
                prNumber,
                status,
                result.returnMessages(),
                result.durationMs(),
                result.errorType()
        );
    }

    public static ActionResult success(
            String traceId,
            String capabilityId,
            String prNumber,
            List<SapReturnMessage> returnMessages,
            long durationMs
    ) {
        return new ActionResult(
                traceId,
                capabilityId,
                true,
                prNumber,
                CommitStatus.committed,
                returnMessages,
                durationMs,
                ErrorType.NONE
        );
    }

    public static ActionResult failure(
            String traceId,
            String capabilityId,
            ErrorType errorType,
            String message,
            long durationMs
    ) {
        return new ActionResult(
                traceId,
                capabilityId,
                false,
                "",
                CommitStatus.none,
                List.of(new SapReturnMessage("E", "", "", message, "")),
                durationMs,
                errorType
        );
    }

    private static CommitStatus commitStatusFrom(ExecutionResult result) {
        Object rawStatus = result.data().get("commitStatus");
        if (rawStatus == null) {
            return CommitStatus.none;
        }
        try {
            return CommitStatus.valueOf(String.valueOf(rawStatus));
        } catch (IllegalArgumentException exception) {
            return CommitStatus.none;
        }
    }
}
