package com.sapnexus.gateway.registry;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.regex.PatternSyntaxException;

public class CapabilityRegistryValidator {
    public void validate(CapabilityRegistry registry) {
        if (registry.version() < 1) {
            throw new RegistryValidationException("version is required");
        }
        if (registry.allCapabilities() == null || registry.allCapabilities().isEmpty()) {
            throw new RegistryValidationException("capabilities are required");
        }

        Set<String> ids = new HashSet<>();
        for (CapabilityDefinition capability : registry.allCapabilities()) {
            validateCapability(capability);
            if (!ids.add(capability.capabilityId())) {
                throw new RegistryValidationException("Duplicate capabilityId: " + capability.capabilityId());
            }
        }
    }

    private void validateCapability(CapabilityDefinition capability) {
        requireText(capability.capabilityId(), "capabilityId");
        requireText(capability.name(), "name");
        requireText(capability.description(), "description");
        requireText(capability.domain(), "domain");
        requireText(capability.businessObject(), "businessObject");
        requireText(capability.ontologyIri(), "ontologyIri");
        requireText(capability.semanticType(), "semanticType");
        require(capability.status(), "status");
        require(capability.kind(), "kind");
        requireNotEmpty(capability.inputs(), "inputs");
        requireNotEmpty(capability.outputs(), "outputs");
        require(capability.executor(), "executor");
        requireText(capability.executor().type(), "executor.type");
        String executorType = capability.executor().type();
        if ("JCO_RFC".equals(executorType)) {
            requireText(capability.executor().rfcName(), "executor.rfcName");
            requireMap(capability.executor().inputMapping(), "executor.inputMapping");
            requireMap(capability.executor().outputMapping(), "executor.outputMapping");
        }
        require(capability.executorBinding(), "executorBinding");
        requireText(capability.executorBinding().type(), "executorBinding.type");
        requireText(capability.executorBinding().bindingId(), "executorBinding.bindingId");
        if (!capability.executorBinding().type().equals(executorType)) {
            throw new RegistryValidationException("executorBinding.type must match executor.type: " + capability.capabilityId());
        }
        require(capability.governance(), "governance");
        require(capability.governance().sideEffect(), "governance.sideEffect");

        if (capability.kind() == CapabilityKind.Function && capability.governance().sideEffect() != SideEffect.none) {
            throw new RegistryValidationException("Function capability must have sideEffect=none: " + capability.capabilityId());
        }
        if (capability.kind() == CapabilityKind.Action && !capability.governance().requiresApproval()) {
            throw new RegistryValidationException("Action capability must require human approval: " + capability.capabilityId());
        }
        for (CapabilityDefinition.InputField input : capability.inputs()) {
            validatePattern(input);
        }
    }

    private void validatePattern(CapabilityDefinition.InputField input) {
        if (input.pattern() == null) {
            return;
        }
        try {
            Pattern.compile(input.pattern());
        } catch (PatternSyntaxException e) {
            throw new RegistryValidationException("Invalid input pattern: " + input.name());
        }
    }

    private void require(Object value, String field) {
        if (value == null) {
            throw new RegistryValidationException(field + " is required");
        }
    }

    private void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new RegistryValidationException(field + " is required");
        }
    }

    private void requireNotEmpty(List<?> value, String field) {
        if (value == null || value.isEmpty()) {
            throw new RegistryValidationException(field + " is required");
        }
    }

    private void requireMap(java.util.Map<?, ?> value, String field) {
        if (value == null || value.isEmpty()) {
            throw new RegistryValidationException(field + " is required");
        }
    }
}
