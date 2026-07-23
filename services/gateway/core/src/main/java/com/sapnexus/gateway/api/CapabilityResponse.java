package com.sapnexus.gateway.api;

import com.sapnexus.gateway.result.ErrorType;

import java.util.List;

public record CapabilityResponse(
        String traceId,
        String capabilityId,
        boolean success,
        ErrorType errorType,
        List<String> messages
) {
    public static CapabilityResponse success(String traceId, String capabilityId) {
        return new CapabilityResponse(traceId, capabilityId, true, ErrorType.NONE, List.of());
    }

    public static CapabilityResponse failure(String traceId, String capabilityId, ErrorType errorType, String message) {
        return new CapabilityResponse(traceId, capabilityId, false, errorType, List.of(message));
    }
}
