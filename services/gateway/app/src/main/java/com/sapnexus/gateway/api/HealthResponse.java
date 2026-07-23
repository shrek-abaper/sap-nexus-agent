package com.sapnexus.gateway.api;

public record HealthResponse(
        String status,
        String gateway,
        boolean jcoConfigured,
        boolean sapEnvironmentPresent,
        boolean sensitiveFieldsExposed
) {
}
