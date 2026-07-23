package com.sapnexus.gateway.jco;

import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.result.ExecutionResult;

import java.util.Map;

public interface JcoCapabilityExecutor {
    ExecutionResult execute(CapabilityDefinition capability, Map<String, Object> parameters, String traceId);
}
