package com.sapnexus.gateway.api;

import com.sapnexus.gateway.jco.JcoDestinationProperties;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {
    @GetMapping("/health")
    public HealthResponse health() {
        JcoDestinationProperties properties = JcoDestinationProperties.fromEnvironment();
        return new HealthResponse(
                "UP",
                "sap-nexus-jco-gateway",
                properties.jcoConfigured(),
                properties.sapEnvironmentPresent(),
                false
        );
    }
}
