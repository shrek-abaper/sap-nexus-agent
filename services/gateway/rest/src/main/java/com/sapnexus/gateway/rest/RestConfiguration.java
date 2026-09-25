package com.sapnexus.gateway.rest;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(Rest2RfcProperties.class)
public class RestConfiguration {
}
