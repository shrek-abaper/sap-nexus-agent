package com.sapnexus.gateway.registry;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.nio.file.Path;

@Configuration
@EnableConfigurationProperties(RegistryProperties.class)
public class RegistryConfiguration {
    @Bean
    CapabilityRegistry capabilityRegistry(RegistryProperties properties) {
        return new CapabilityRegistryLoader().load(Path.of(properties.getPath()));
    }

    @Bean
    BindingRegistry bindingRegistry(RegistryProperties properties) {
        return new BindingRegistryLoader().load(Path.of(properties.getBindingsPath()));
    }
}
