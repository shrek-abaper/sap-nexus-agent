package com.sapnexus.gateway.registry;

import java.util.List;
import java.util.Optional;

public record BindingRegistry(int version, List<BindingDefinition> allBindings) {
    public Optional<BindingDefinition> find(String bindingId) {
        if (bindingId == null) {
            return Optional.empty();
        }
        return allBindings.stream()
                .filter(binding -> bindingId.equals(binding.bindingId()))
                .findFirst();
    }
}
