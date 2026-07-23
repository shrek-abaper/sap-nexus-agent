package com.sapnexus.gateway.execution;

import java.util.LinkedHashMap;
import java.util.Map;

public final class TechnicalRedactor {
    private static final String SENSITIVE_TEXT_KEY =
            "(?:passwd|password|token|secret|credential|authorization|api[-_ ]?key|"
                    + "destination|ashost|mshost|gwhost|sysnr|client|user)";
    private static final String SENSITIVE_FREE_TEXT_KEY =
            "(?:passwd|password|token|secret|credential|authorization|api[-_ ]?key|"
                    + "destination|ashost|mshost|gwhost)";

    private TechnicalRedactor() {
    }

    public static Map<String, Object> redactMap(Map<String, Object> input) {
        Map<String, Object> redacted = new LinkedHashMap<>();
        if (input == null) {
            return redacted;
        }
        input.forEach((key, value) -> redacted.put(key, redactValue(key, value)));
        return redacted;
    }

    @SuppressWarnings("unchecked")
    public static Object redactValue(String key, Object value) {
        if (isSensitiveKey(key)) {
            return "***";
        }
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> nested = new LinkedHashMap<>();
            map.forEach((nestedKey, nestedValue) -> {
                String nestedName = String.valueOf(nestedKey);
                nested.put(nestedName, redactValue(nestedName, nestedValue));
            });
            return nested;
        }
        if (value instanceof String text) {
            return redactText(text);
        }
        return value;
    }

    public static String redactText(String text) {
        if (text == null) {
            return "";
        }
        String redacted = text.replaceAll(
                "(?i)(\\b" + SENSITIVE_TEXT_KEY
                        + "\\b[\"']?\\s*(?:=|:)\\s*(?:(?:Bearer|Basic)\\s+)?)"
                        + "(?:\"[^\"]*\"|'[^']*'|[^\\s,;\"'}]+)",
                "$1***");
        return redacted.replaceAll(
                "(?i)(\\b" + SENSITIVE_FREE_TEXT_KEY
                        + "\\b\\s+(?:(?:Bearer|Basic)\\s+)?)"
                        + "(?:\"[^\"]*\"|'[^']*'|[^\\s,;]+)",
                "$1***");
    }

    public static boolean isSensitiveKey(String key) {
        String normalized = key == null ? "" : key.replace("_", "").replace("-", "").replace(" ", "").toLowerCase();
        return normalized.contains("password")
                || normalized.contains("passwd")
                || normalized.contains("token")
                || normalized.contains("secret")
                || normalized.contains("credential")
                || normalized.contains("authorization")
                || normalized.contains("apikey")
                || normalized.contains("destination")
                || normalized.contains("endpoint")
                || normalized.equals("url")
                || normalized.contains("serviceurl")
                || normalized.contains("header")
                || normalized.contains("config")
                || normalized.equals("env")
                || normalized.equals("environment")
                || normalized.equals("rfcname")
                || normalized.equals("rawsql")
                || normalized.equals("sql")
                || normalized.contains("cookie");
    }
}
