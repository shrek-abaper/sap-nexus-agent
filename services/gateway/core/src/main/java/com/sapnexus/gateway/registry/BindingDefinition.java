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
        Map<String, Object> constraints
) {
}
