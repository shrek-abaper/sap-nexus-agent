package com.sapnexus.gateway.jco;

import java.util.List;
import java.util.Map;
import java.util.Objects;

public record JcoDestinationProperties(
        boolean sapEnvironmentPresent,
        boolean jcoConfigured,
        List<String> missingRequiredKeys,
        String safeSummary
) {
    private static final List<String> REQUIRED_KEYS = List.of(
            "SAP_ASHOST",
            "SAP_SYSNR",
            "SAP_CLIENT",
            "SAP_USER",
            "SAP_PASSWORD",
            "SAP_LANG"
    );

    public static JcoDestinationProperties fromEnvironment() {
        return from(System.getenv());
    }

    public static JcoDestinationProperties from(Map<String, String> env) {
        List<String> missing = REQUIRED_KEYS.stream()
                .filter(key -> isBlank(env.get(key)))
                .toList();
        boolean sapEnvironmentPresent = missing.isEmpty();
        boolean jcoConfigured = sapEnvironmentPresent && !isBlank(env.get("SAP_JCO_LIB_PATH"));
        String summary = "sapEnvironmentPresent=" + sapEnvironmentPresent
                + ", jcoConfigured=" + jcoConfigured
                + ", missingRequiredKeys=" + missing;
        return new JcoDestinationProperties(sapEnvironmentPresent, jcoConfigured, missing, summary);
    }

    private static boolean isBlank(String value) {
        return Objects.toString(value, "").isBlank();
    }
}
