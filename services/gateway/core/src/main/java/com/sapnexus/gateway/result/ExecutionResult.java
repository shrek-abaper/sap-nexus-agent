package com.sapnexus.gateway.result;

import java.util.List;
import java.util.Map;

public record ExecutionResult(
        String traceId,
        String capabilityId,
        boolean success,
        ExecutorMetadata executor,
        List<SapReturnMessage> returnMessages,
        Map<String, Object> data,
        long durationMs,
        ErrorType errorType
) {
    public static ExecutionResult success(
            String traceId,
            String capabilityId,
            String executorType,
            String rfcName,
            List<SapReturnMessage> returnMessages,
            Map<String, Object> data,
            long durationMs
    ) {
        return new ExecutionResult(
                traceId,
                capabilityId,
                true,
                new ExecutorMetadata(executorType, rfcName),
                returnMessages,
                data,
                durationMs,
                ErrorType.NONE
        );
    }

    public static ExecutionResult failure(
            String traceId,
            String capabilityId,
            String executorType,
            String rfcName,
            ErrorType errorType,
            String message,
            long durationMs
    ) {
        return new ExecutionResult(
                traceId,
                capabilityId,
                false,
                new ExecutorMetadata(executorType, rfcName),
                List.of(new SapReturnMessage("E", "", "", message, "")),
                Map.of(),
                durationMs,
                errorType
        );
    }

    public record ExecutorMetadata(String type, String rfcName) {
    }
}
