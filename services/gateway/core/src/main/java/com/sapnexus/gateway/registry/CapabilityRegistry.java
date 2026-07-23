package com.sapnexus.gateway.registry;

import java.util.List;
import java.util.Optional;

public record CapabilityRegistry(int version, List<CapabilityDefinition> allCapabilities) {
    public List<CapabilityDefinition> enabledCapabilities() {
        return allCapabilities.stream()
                .filter(capability -> capability.status() == CapabilityStatus.active)
                .toList();
    }

    public Optional<CapabilityDefinition> findEnabled(String capabilityId) {
        return enabledCapabilities().stream()
                .filter(capability -> capability.capabilityId().equals(capabilityId))
                .findFirst();
    }

    public Optional<CapabilityDefinition> findAny(String capabilityId) {
        return allCapabilities.stream()
                .filter(capability -> capability.capabilityId().equals(capabilityId))
                .findFirst();
    }
}
