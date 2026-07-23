package com.sapnexus.gateway.execution;

import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnMessage;

import java.util.List;
import java.util.Map;

public record TechnicalExecutionResult(
        String traceId,
        String capabilityId,
        String bindingId,
        String executorType,
        boolean success,
        ErrorType errorType,
        List<SapReturnMessage> messages,
        Map<String, Object> data,
        long durationMs,
        boolean redactionApplied,
        Map<String, Object> adapterMetadata
) {
    public static TechnicalExecutionResult success(
            String traceId,
            String capabilityId,
            String bindingId,
            String executorType,
            List<SapReturnMessage> messages,
            Map<String, Object> data,
            long durationMs,
            Map<String, Object> adapterMetadata
    ) {
        return new TechnicalExecutionResult(
                traceId,
                capabilityId,
                bindingId,
                executorType,
                true,
                ErrorType.NONE,
                messages,
                data,
                durationMs,
                true,
                TechnicalRedactor.redactMap(adapterMetadata)
        );
    }

    public static TechnicalExecutionResult failure(
            String traceId,
            String capabilityId,
            String bindingId,
            String executorType,
            ErrorType errorType,
            String message,
            long durationMs
    ) {
        return new TechnicalExecutionResult(
                traceId,
                capabilityId,
                bindingId,
                executorType,
                false,
                errorType,
                List.of(new SapReturnMessage("E", "", "", TechnicalRedactor.redactText(message), "")),
                Map.of(),
                durationMs,
                true,
                Map.of()
        );
    }

    public static TechnicalExecutionResult fromExecutionResult(String bindingId, ExecutionResult result) {
        return new TechnicalExecutionResult(
                result.traceId(),
                result.capabilityId(),
                bindingId,
                result.executor().type(),
                result.success(),
                result.errorType(),
                result.returnMessages(),
                result.data(),
                result.durationMs(),
                true,
                TechnicalRedactor.redactMap(Map.of("rfcName", result.executor().rfcName()))
        );
    }

    public ExecutionResult toExecutionResult(CapabilityDefinition capability) {
        String rfcName = capability.executor() != null ? capability.executor().rfcName() : null;
        return new ExecutionResult(
                traceId,
                capabilityId,
                success,
                new ExecutionResult.ExecutorMetadata(executorType, rfcName),
                messages,
                data,
                durationMs,
                errorType
        );
    }
}
