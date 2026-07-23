package com.sapnexus.gateway.execution;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Map;

@Configuration
public class ExecutionConfiguration {

    @Bean
    TechnicalExecutionDispatcher technicalExecutionDispatcher(Map<String, TechnicalAdapter> adapters) {
        return new TechnicalExecutionDispatcher(adapters);
    }
}
