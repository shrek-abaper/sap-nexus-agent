package com.sapnexus.gateway.execution;

import java.util.Map;

public record TechnicalExecutionRequest(
        String traceId,
        String capabilityId,
        String bindingId,
        String executorType,
        String operation,
        Map<String, Object> parameters,
        Map<String, Object> constraints,
        Map<String, Object> callerContext
) {
}
