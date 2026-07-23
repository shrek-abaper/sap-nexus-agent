package com.sapnexus.gateway.trace;

import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.ActionResult;
import com.sapnexus.gateway.result.SapReturnMessage;
import com.sapnexus.gateway.execution.TechnicalRedactor;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public record TraceRecord(
        String traceId,
        String timestamp,
        String operation,
        String capabilityId,
        Map<String, Object> parameterSummary,
        Map<String, Object> resultSummary,
        boolean success,
        long durationMs,
        ErrorType errorType
) {
    public static TraceRecord of(
            String traceId,
            String operation,
            String capabilityId,
            Map<String, Object> parameters,
            boolean success,
            long durationMs,
            ErrorType errorType
    ) {
        return new TraceRecord(
                traceId,
                Instant.now().toString(),
                operation,
                capabilityId,
                summarize(parameters),
                Map.of(),
                success,
                durationMs,
                errorType
        );
    }

    public static TraceRecord ofAction(
            String traceId,
            String operation,
            String capabilityId,
            Map<String, Object> parameters,
            ActionResult result
    ) {
        return new TraceRecord(
                traceId,
                Instant.now().toString(),
                operation,
                capabilityId,
                summarize(parameters),
                summarize(result),
                result.success(),
                result.durationMs(),
                result.errorType()
        );
    }

    private static Map<String, Object> summarize(ActionResult result) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("prNumber", TechnicalRedactor.redactText(result.prNumber()));
        summary.put("commitStatus", result.commitStatus().name());
        List<Map<String, String>> returnMessages = new ArrayList<>();
        for (SapReturnMessage message : result.returnMessages()) {
            Map<String, String> sanitized = new LinkedHashMap<>();
            sanitized.put("type", TechnicalRedactor.redactText(message.type()));
            sanitized.put("id", TechnicalRedactor.redactText(message.id()));
            sanitized.put("number", TechnicalRedactor.redactText(message.number()));
            sanitized.put("message", TechnicalRedactor.redactText(message.message()));
            sanitized.put("field", TechnicalRedactor.redactText(message.field()));
            returnMessages.add(sanitized);
        }
        summary.put("returnMessages", returnMessages);
        return summary;
    }

    private static Map<String, Object> summarize(Map<String, Object> parameters) {
        Map<String, Object> summary = new LinkedHashMap<>();
        if (parameters == null) {
            return summary;
        }
        parameters.forEach((key, value) -> {
            if (isUnsafeKey(key)) {
                return;
            }
            Object sanitized = sanitizeValue(value);
            if (sanitized != null) {
                summary.put(key, sanitized);
            }
        });
        return summary;
    }

    @SuppressWarnings("unchecked")
    private static Object sanitizeValue(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> sanitized = new LinkedHashMap<>();
            map.forEach((nestedKey, nestedValue) -> {
                String key = String.valueOf(nestedKey);
                if (!isUnsafeKey(key)) {
                    Object sanitizedValue = sanitizeValue(nestedValue);
                    if (sanitizedValue != null) {
                        sanitized.put(key, sanitizedValue);
                    }
                }
            });
            return sanitized.isEmpty() ? null : sanitized;
        }
        if (value instanceof Iterable<?>) {
            return null;
        }
        return value;
    }

    private static boolean isUnsafeKey(String key) {
        String normalized = key == null ? "" : key.toLowerCase();
        return normalized.startsWith("sap_") || TechnicalRedactor.isSensitiveKey(key);
    }
}
