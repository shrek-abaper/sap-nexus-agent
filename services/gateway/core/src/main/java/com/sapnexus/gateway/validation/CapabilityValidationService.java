package com.sapnexus.gateway.validation;

import com.sapnexus.gateway.api.CapabilityResponse;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.result.ErrorType;

import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;

public class CapabilityValidationService {
    private final CapabilityRegistry registry;

    public CapabilityValidationService(CapabilityRegistry registry) {
        this.registry = registry;
    }

    public CapabilityResponse validate(String capabilityId, Map<String, Object> parameters) {
        String traceId = UUID.randomUUID().toString();
        return registry.findAny(capabilityId)
                .map(capability -> validateCapability(traceId, capability, parameters))
                .orElseGet(() -> CapabilityResponse.failure(traceId, capabilityId, ErrorType.CAPABILITY_NOT_FOUND, "Capability is not registered"));
    }

    private CapabilityResponse validateCapability(String traceId, CapabilityDefinition capability, Map<String, Object> parameters) {
        if (capability.status() != CapabilityStatus.active) {
            return CapabilityResponse.failure(traceId, capability.capabilityId(), ErrorType.CAPABILITY_DISABLED, "Capability is disabled");
        }
        for (CapabilityDefinition.InputField input : capability.inputs()) {
            Object value = parameters.get(input.name());
            if (input.required() && isBlank(value)) {
                return CapabilityResponse.failure(traceId, capability.capabilityId(), ErrorType.MISSING_PARAMETER, "Missing required parameter: " + input.name());
            }
            if (value != null && !isValid(input, value)) {
                return CapabilityResponse.failure(traceId, capability.capabilityId(), ErrorType.INVALID_PARAMETER, "Invalid parameter: " + input.name());
            }
        }
        return CapabilityResponse.success(traceId, capability.capabilityId());
    }

    private boolean isBlank(Object value) {
        return value == null || String.valueOf(value).isBlank();
    }

    private boolean isValid(CapabilityDefinition.InputField input, Object value) {
        if ("string".equals(input.type()) && !(value instanceof String)) {
            return false;
        }
        String text = String.valueOf(value);
        if (input.minLength() != null && text.length() < input.minLength()) {
            return false;
        }
        if (input.maxLength() != null && text.length() > input.maxLength()) {
            return false;
        }
        return input.pattern() == null || Pattern.matches(input.pattern(), text);
    }
}
