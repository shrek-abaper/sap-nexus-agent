package com.sapnexus.gateway.trace;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.nio.file.Path;

@Configuration
@EnableConfigurationProperties(TraceProperties.class)
public class TraceConfiguration {
    @Bean
    TraceWriter traceWriter(TraceProperties properties) {
        return new TraceWriter(Path.of(properties.getPath()));
    }
}
