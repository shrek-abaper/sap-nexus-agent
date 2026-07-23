package com.sapnexus.gateway.api;

import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

public record CapabilityRequest(
        Map<String, Object> parameters,
        String approvalId,
        String parameterSnapshotHash
) {
    public CapabilityRequest(Map<String, Object> parameters) {
        this(parameters, null, null);
    }

    public Map<String, Object> safeParameters() {
        return parameters == null ? Map.of() : parameters;
    }

    public Set<String> technicalOverrideKeys() {
        if (parameters == null) {
            return Set.of();
        }
        Set<String> matches = new LinkedHashSet<>();
        parameters.keySet().forEach(key -> collectTechnicalOverride(matches, key));
        return matches;
    }

    private static void collectTechnicalOverride(Set<String> matches, String key) {
        String normalized = key == null ? "" : key.replace("_", "").replace("-", "").replace("$", "").toLowerCase();
        if (normalized.equals("rfcname")
                || normalized.contains("serviceurl")
                || normalized.contains("servicepath")
                || normalized.contains("restendpoint")
                || normalized.contains("endpoint")
                || normalized.equals("url")
                || normalized.equals("httpmethod")
                || normalized.equals("method")
                || normalized.equals("headers")
                || normalized.equals("credentialref")
                || normalized.contains("credentials")
                || normalized.contains("jsonmapping")
                || normalized.equals("rawsql")
                || normalized.equals("sql")
                || normalized.equals("adtpath")
                || normalized.equals("cdsobject")
                || normalized.equals("cdsentity")
                || normalized.contains("filter")
                || normalized.contains("entityset")
                || normalized.contains("serviceref")
                || normalized.contains("selectfields")
                || normalized.contains("toplimit")
                // OData URL-level system query options ($select/$top/$skip/$expand/$count);
                // binding-level selectFields/topLimit covered above, these guard the $-prefixed variants
                || normalized.equals("select")
                || normalized.equals("top")
                || normalized.equals("skip")
                || normalized.equals("expand")
                || normalized.equals("count")
                // technical security fields redacted downstream but not previously blocked at the guard
                || normalized.contains("baseurl")
                || normalized.contains("sapclient")
                || normalized.contains("csrf")
                || normalized.contains("token")
                || normalized.contains("authorization")
                || normalized.contains("destination")) {
            matches.add(key);
        }
    }
}
