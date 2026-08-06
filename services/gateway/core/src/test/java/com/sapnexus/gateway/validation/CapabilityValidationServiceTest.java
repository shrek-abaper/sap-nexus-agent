package com.sapnexus.gateway.validation;

import com.sapnexus.gateway.api.CapabilityResponse;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityRegistryLoader;
import com.sapnexus.gateway.result.ErrorType;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class CapabilityValidationServiceTest {
    @Test
    void rejectsPlantThatDoesNotMatchTheRegistryPattern() {
        CapabilityValidationService service = new CapabilityValidationService(loadRegistry());

        CapabilityResponse response = service.validate(
                "MM.Inventory.GetAvailability",
                Map.of("material", "1000", "plant", "\u5de5\u5382"));

        assertThat(response.success()).isFalse();
        assertThat(response.errorType()).isEqualTo(ErrorType.INVALID_PARAMETER);
        assertThat(response.messages()).containsExactly("Invalid parameter: plant");
    }

    private static CapabilityRegistry loadRegistry() {
        Path dir = Path.of(System.getProperty("user.dir"));
        while (dir != null && !Files.exists(dir.resolve("registry/capabilities.yaml"))) {
            dir = dir.getParent();
        }
        if (dir == null) {
            throw new IllegalStateException(
                    "registry/capabilities.yaml not found from " + System.getProperty("user.dir"));
        }
        return new CapabilityRegistryLoader().load(dir.resolve("registry/capabilities.yaml"));
    }
}
