package com.sapnexus.gateway.registry;

import java.util.List;
import java.util.Map;

/**
 * Declares how a capability binding is executed.
 *
 * <p>ODATA bindings populate {@code serviceRef}/{@code entitySet}/{@code method}/
 * {@code filterMapping}/{@code topLimit}/{@code selectFields}; JCO bindings leave
 * those null and rely on {@code rfcName}/{@code allowedImports}/{@code allowedOutputs}
 * (not modelled here -- JCo does not use {@link BindingRegistry}).
 *
 * <p>REST_JSON bindings populate {@code systemRef}/{@code pathTemplate}/
 * {@code request}/{@code response}/{@code auth}; connection values and credentials
 * are resolved from Gateway-controlled configuration, never from these fields.
 */
public record BindingDefinition(
        String bindingId,
        String type,
        String serviceRef,
        String entitySet,
        String method,
        Map<String, String> filterMapping,
        Integer topLimit,
        List<String> selectFields,
        Map<String, Object> constraints,
        String systemRef,
        String pathTemplate,
        Map<String, Object> request,
        Map<String, Object> response,
        Map<String, Object> auth
) {
    /** Convenience constructor for bindings without REST fields. */
    public BindingDefinition(
            String bindingId,
            String type,
            String serviceRef,
            String entitySet,
            String method,
            Map<String, String> filterMapping,
            Integer topLimit,
            List<String> selectFields,
            Map<String, Object> constraints
    ) {
        this(bindingId, type, serviceRef, entitySet, method, filterMapping, topLimit,
                selectFields, constraints, null, null, Map.of(), Map.of(), Map.of());
    }
}
